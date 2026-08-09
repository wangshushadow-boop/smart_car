## 进入ros环境
source /opt/ros/kilted/setup.zsh
source /mnt/d/work/smart_car/robot_host/install-ros/setup.zsh
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

## rqt 
以黑色主题，1.5倍的窗口大小打开窗口
```zsh
QT_QPA_PLATFORMTHEME=qt5ct \
QT_SCALE_FACTOR=1.5 \
rqt
```
清空rqt缓存，并启动
```zsh
rqt --clear-config --force-discover
```