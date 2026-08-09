FROM ros:kilted-ros-base

# 树莓派使用 ARM64 Ubuntu Ports；切换到国内镜像以加快 Docker 构建。
# ROS 2 软件包使用独立镜像，pip 在下方继续使用清华 PyPI。
ARG UBUNTU_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports
ARG ROS2_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu

RUN sed -i \
      "s|http://ports.ubuntu.com/ubuntu-ports|${UBUNTU_MIRROR}|g" \
      /etc/apt/sources.list.d/ubuntu.sources \
    && sed -i \
      -e "s|Types: deb deb-src|Types: deb|g" \
      -e "s|http://packages.ros.org/ros2/ubuntu|${ROS2_MIRROR}|g" \
      /etc/apt/sources.list.d/ros2.sources

RUN apt-get update && apt-get install -y --no-install-recommends \
      libyaml-cpp-dev \
      libasound2-dev \
      alsa-utils \
      libportaudio2 \
      mpg123 \
      python3-numpy \
      python3-yaml \
      python3-colcon-common-extensions \
      python3-pip \
      ros-kilted-ament-index-python \
      ros-kilted-diagnostic-msgs \
      ros-kilted-nav-msgs \
      ros-kilted-nav2-msgs \
      ros-kilted-navigation2 \
      ros-kilted-nav2-bringup \
      ros-kilted-robot-state-publisher \
      ros-kilted-robot-localization \
      ros-kilted-rmw-cyclonedds-cpp \
      ros-kilted-v4l2-camera \
      ros-kilted-image-transport-plugins \
      ros-kilted-sensor-msgs \
      ros-kilted-std-msgs \
      ros-kilted-std-srvs \
      ros-kilted-tf2-ros \
      ros-kilted-trajectory-msgs \
      ros-kilted-xacro \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --break-system-packages --no-cache-dir \
      --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
      --timeout 120 --retries 10 sounddevice

WORKDIR /workspace/smart_car
