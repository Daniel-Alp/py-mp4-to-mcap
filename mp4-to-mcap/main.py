import argparse
import av
import subprocess
from pathlib import Path
from foxglove_schemas_protobuf.CompressedVideo_pb2 import CompressedVideo
from google.protobuf.timestamp_pb2 import Timestamp
from mcap_protobuf.writer import Writer
from tempfile import NamedTemporaryFile

def mp4_to_mcap(input_path: Path, output_path: Path, topic: str, frame_id: str):
    with av.open(input_path, "r") as container:
        video_stream = container.streams.video[0]
        codec_context = video_stream.codec_context
        codec_name = codec_context.name
        if codec_name not in ["h264", "h265", "hevc"]:
            raise ValueError(f"Unsupported codec: {codec_name}")
    
    with NamedTemporaryFile(suffix=".ts", delete=False) as temp_output:
        temp_output_path = Path(temp_output.name)
    
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-c:v", "libx264" if codec_name == "h264" else "libx265",
        "-bf", "0",
        "-bsf:v", "h264_mp4toannexb" if codec_name == "h264" else "hevc_mp4toannexb",
        str(temp_output_path)
    ]
    subprocess.run(cmd, check=True)

    with av.open(temp_output_path, "r") as container, open(output_path, "wb") as stream, Writer(stream) as writer:
        video_stream = container.streams.video[0]
        codec_context = video_stream.codec_context

        format = "h264" if codec_name == "h264" else "h265"

        for packet in container.demux(video_stream):
            if packet.pts is None:
                continue
            data = bytes(packet)
            # assumes that 1 packet corresponds to 1 frame https://ffmpeg.org/doxygen/2.0/structAVPacket.html
            timestamp_ns = int(packet.pts * 1_000_000_000 * packet.time_base.numerator / packet.time_base.denominator)
            message = CompressedVideo(
                timestamp   = Timestamp(seconds=timestamp_ns // 1_000_000_000, nanos=timestamp_ns % 1_000_000_000),
                data        = data,
                format      = format
            )
            writer.write_message(
                topic        = topic,
                message      = message,
                publish_time = timestamp_ns,
                log_time     = timestamp_ns
            )

    temp_output_path.unlink()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Converts MP4 videos to MCAP")
    parser.add_argument("--topic", type=str, default="video", help="Topic name for the video messages [default: video]")
    parser.add_argument("--frame-id", type=str, default="video", help="Frame ID for the video messages [default: video]")
    parser.add_argument("INPUT", type=Path, help="Input MP4 file")
    parser.add_argument("OUTPUT", type=Path, help="Output MCAP file")
    args = parser.parse_args()
    mp4_to_mcap(args.INPUT, args.OUTPUT, args.topic, args.frame_id)