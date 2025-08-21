import argparse
from pathlib import Path
from codec import VideoConverter
from foxglove_schemas_protobuf.CompressedVideo_pb2 import CompressedVideo
from google.protobuf.timestamp_pb2 import Timestamp
from mcap_protobuf.writer import Writer

def convert_mp4_to_mcap(input_path: Path, output_path: Path, topic: str, frame_id: str):
    print(f"Converting {input_path} to {output_path}")

    with VideoConverter(input_path) as converter:
        video_stream = converter.video_stream
        video_stream_index = video_stream.index
    
        first_frame = True
        with open(output_path, "wb") as stream, Writer(stream) as writer:
            for packet in converter.container.demux(video_stream):
                if packet.stream.index != video_stream_index or packet.pts is None:
                    continue

                timestamp_ns = converter.get_timestamp(packet.pts)
                converter.process_packet(packet, is_first=first_frame)
                frames = converter.decode_packet(packet)

                for frame in frames:
                    converter.check_timestamp(timestamp_ns)

                    message = CompressedVideo(
                        frame_id    = frame_id,
                        timestamp   = Timestamp(seconds = timestamp_ns // 1_000_000_000, nanos = timestamp_ns % 1_000_000_000),
                        data        = converter.take_frame_data(),
                        format      = converter.format_str()
                    )
                    writer.write_message(
                        topic        = topic,
                        message      = message,
                        log_time     = timestamp_ns,
                        publish_time = timestamp_ns
                    )
                first_frame = False

            for frame in converter.flush_decoder():
                pass 

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Converts MP4 videos to MCAP")
    parser.add_argument("--topic", type=str, default="video", help="Topic name for the video messages [default: video]")
    parser.add_argument("--frame-id", type=str, default="video", help="Frame ID for the video messages [default: video]")
    parser.add_argument("INPUT", type=Path, help="Input MP4 file")
    parser.add_argument("OUTPUT", type=Path, help="Output MCAP file")
    args = parser.parse_args()
    convert_mp4_to_mcap(args.INPUT, args.OUTPUT, args.topic, args.frame_id)