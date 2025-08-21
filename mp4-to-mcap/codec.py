import av
from av.packet import Packet
from enum import Enum
from dataclasses import dataclass
from pathlib import Path

class CodecType(Enum):
    H264 = "h264"
    H265 = "h265"

    @staticmethod
    def from_ffmpeg_id(codec_name: str): 
        codec_name = codec_name.lower()
        if codec_name == "h264":
            return CodecType.H264
        elif codec_name in ("h265", "hevc"):
            return CodecType.H265
        raise ValueError(f"Unsupported codec: {codec_name}")
    
    def encoder_lib(self) -> str:
        match self:
            case CodecType.H264:
                return "libx264"
            case CodecType.H265:
                return "libx265"
            
    def should_skip_nal(self, nal: int) -> str:
        match self:
            case CodecType.H264:
                H264_NAL_SPS = 0x7
                H264_NAL_PPS = 0x8
                H264_NAL_SEI = 0x6
                return nal == H264_NAL_SPS or nal == H264_NAL_PPS or nal == H264_NAL_SEI
            case CodecType.H265:           
                H265_NAL_VPS = 32
                H265_NAL_SPS = 33
                H265_NAL_PPS = 34
                H265_NAL_SEI = 39   
                return nal == H265_NAL_VPS or nal == H265_NAL_SPS or nal == H265_NAL_PPS or nal == H265_NAL_SEI

@dataclass
class ParameterSets:
    AVCC_HEADER_SIZE = 5
    HVCC_HEADER_SIZE = 22

    vps: bytearray
    sps: bytearray
    pps: bytearray

    @classmethod
    def parse(cls, extradata: bytearray, codec: CodecType) -> 'ParameterSets':
        match codec:
            case CodecType.H264:
                return cls.parse_avcc(extradata)
            case CodecType.H265:
                raise NotImplementedError("TODO: support H265")

    @classmethod
    def parse_avcc(cls, extradata: bytearray):
        if len(extradata) < cls.AVCC_HEADER_SIZE + 2: 
            raise ValueError("AVCC header too short")
        
        offset = cls.AVCC_HEADER_SIZE
        sps_nals = bytearray()
        pps_nals = bytearray()

        num_sps = extradata[offset] & 0x1F
        offset += 1
        for _ in range(num_sps):
            if offset + 2 > len(extradata):
                raise ValueError("Invalid SPS length")
            sps_size = (extradata[offset] << 8) | (extradata[offset+1])
            offset += 2
            if offset + sps_size > len(extradata):
                raise ValueError("SPS data truncated")
            sps_nals.extend([0, 0, 0, 1]) # Add NAL start code
            sps_nals.extend(extradata[offset:offset+sps_size])
            offset += sps_size
        
        if offset >= len(extradata):
            raise ValueError("Missing PPS")
        num_pps = extradata[offset]
        offset += 1
        for _ in range(num_pps):
            if offset + 2 > len(extradata):
                raise ValueError("Invalid PPS length")
            pps_size = (extradata[offset] << 8) | (extradata[offset+1])
            offset += 2
            if offset + pps_size > len(extradata):
                raise ValueError("PPS data truncated")
            pps_nals.extend([0, 0, 0, 1]) # Add NAL start code
            pps_nals.extend(extradata[offset:offset+pps_size])
            offset += pps_size
        
        if (not sps_nals) or (not pps_nals):
            raise ValueError("Missing required parameter sets")
        
        return cls(vps = bytearray(), sps = sps_nals, pps = pps_nals)
    
    def write_to(self, codec: CodecType, buffer: bytearray):
        if codec == CodecType.H265:
            buffer.extend(self.vps)
        buffer.extend(self.sps)
        buffer.extend(self.pps)  

def convert_to_annex_b(data: bytearray, codec: CodecType) -> bytearray:
    converted = bytearray()
    pos = 0
    while pos < len(data):
        if pos + 4 > len(data):
            break
        nal_size = int.from_bytes(data[pos:pos+4], byteorder='big')

        nal_type = 0 
        if pos + 4 < len(data):
            match codec:
                case CodecType.H264:
                    nal_type = data[pos+4] & 0x1F
                case CodecType.H265:
                    nal_type = (data[pos+4] >> 1) & 0x3F
        
        pos += 4

        if not codec.should_skip_nal(nal_type):
            converted.extend([0, 0, 0, 1])
            if pos + nal_size <= len(data):
                converted.extend(data[pos:pos+nal_size])
        
        if pos + nal_size <= len(data):
            pos += nal_size
        else:
            break

    return converted

class VideoConverter:
    def __init__(self, input_path: Path):
        self.input_path = input_path

    def __enter__(self):
        self.container = av.open(self.input_path, mode="r")
        self.video_stream = next(s for s in self.container.streams if s.type == 'video')
        self.codec_type = CodecType.from_ffmpeg_id(self.video_stream.codec_context.name)        
        self.decoder = self.video_stream.codec_context

        if not self.decoder.extradata:
            raise ValueError("No codec extradata found")
        self.extradata = self.decoder.extradata
        self.parameter_sets = ParameterSets.parse(self.extradata, self.codec_type)

        self.time_base_num = self.video_stream.time_base.numerator
        self.time_base_den = self.video_stream.time_base.denominator

        self.frame_packets: list[bytes] = []
        
        self.last_timestamp_ns = -1
        self.last_progress = 0
        return self

    def __exit__(self, type, value, traceback):
        self.container.close()

    def decode_packet(self, packet: Packet):
        return self.decoder.decode(packet)

    def flush_decoder(self):
        return self.decoder.decode(None)
    
    def process_packet(self, packet: Packet, is_first: bool):
        data = bytes(packet)

        if packet.pts != packet.dts:
            raise ValueError(
                f"This video contains B-frames or reordered frames (PTS={packet.pts}, DTS={packet.dts}). "
                f"Please re-encode the video without B-frames using: "
                f"ffmpeg -i <input> -c:v {self.codec_type.value} -bf 0 output.mp4"
            )
        
        if is_first or packet.is_keyframe:
            frame_data = bytearray()
            self.parameter_sets.write_to(self.codec_type, frame_data)
            converted = convert_to_annex_b(data, self.codec_type)
            frame_data.extend(converted)
            self.frame_packets.append(frame_data)
        else:
            converted = convert_to_annex_b(data, self.codec_type)
            self.frame_packets.append(converted)

    def get_timestamp(self, pts: int) -> int:
        if self.time_base_den == 0:
            return 0
        return int(pts * 1_000_000_000 * self.time_base_num / self.time_base_den)
   
    def take_frame_data(self) -> bytes:
        data = b''.join(self.frame_packets)
        self.frame_packets.clear()
        return data
    
    def format_str(self) -> str:
        return self.codec_type.value
    
    def check_timestamp(self, timestamp_ns: int):
        if timestamp_ns <= self.last_timestamp_ns and self.last_timestamp_ns != -1:
            raise ValueError(f"Non-monotonic timestamp detected: {timestamp_ns} <= {self.last_timestamp_ns}")
        self.last_timestamp_ns = timestamp_ns