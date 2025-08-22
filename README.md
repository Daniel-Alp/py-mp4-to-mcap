# py-mp4-to-mcap
convert MP4s with H264 or H265 video encoding to MCAP.

install ffmpeg
on MacOS
```
brew install pkg-config ffmpeg
```
on Linux
```
sudo apt-get update
sudo apt-get install -qq --no-install-recommends \
  pkg-config \
  ffmpeg \
  libavutil-dev \
  libavcodec-dev \
  libavformat-dev \
  libswscale-dev \
  libswresample-dev \
  libavfilter-dev \
  libavdevice-dev
```
clone the repository, install dependencies
```
git clone https://github.com/Daniel-Alp/py-mp4-to-mcap/tree/main
cd py-mp4-to-mcap
python3 -m pip install -r requirements.txt
```
example of using script
```
python3 mp4-to-mcap/main.py ~/Downloads/Big_Buck_Bunny_1080_10s_1MB.mp4 Big_Buck_Bunny_1080_10s_1MB.mcap
```