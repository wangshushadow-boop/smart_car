from glob import glob

from setuptools import find_packages, setup

package_name = "small_car_av"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="small_car",
    maintainer_email="small-car@example.com",
    description="小车 ROS 2 真实摄像头与麦克风采集节点。",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "jabra_audio_publisher = small_car_av.jabra_audio_publisher:main",
            "jabra_audio_player = small_car_av.jabra_audio_player:main",
        ],
    },
)
