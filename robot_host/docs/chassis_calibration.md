# 小车底盘标定

本文按阶段标定底盘，使速度控制、轮式里程计、IMU、`/odom` 和 TF 满足
Nav2 闭环控制要求。一次只完成一个阶段；未达到当前阶段的通过标准时，不要继续。

## 0. 安全与环境

准备卷尺、胶带、直角标线和可快速断开的电源。使用最终轮胎、载荷和正常电量，
选择至少 3 m × 3 m 的平整防滑地面。标定时不要启动 Nav2 导航任务，并确保
小车前后无人、无障碍物。

在 WSL 的每个终端先执行：

```bash
source /opt/ros/kilted/setup.bash
```

确认 ROS 链路：

```bash
ros2 node list --no-daemon --spin-time 8
ros2 topic hz /wheel/odom_raw
ros2 topic echo /diagnostics --once
```

应看到 `/small_car_base` 和 `/ekf_filter_node`，里程计频率约 30～40 Hz，诊断中
没有串口、编码器或 IMU 错误。

启动完整 Nav2 系统时，手工测试命令必须发到 `/cmd_vel_nav`，让命令经过
`velocity_smoother` 和 `collision_monitor`。`/cmd_vel` 是最终底盘输出，存在多个
系统发布者，不应同时用命令行向它写入。仅启动 `base.launch.py` 时才直接使用
`/cmd_vel`。

启动参数界面和曲线：

```bash
ros2 run rqt_reconfigure rqt_reconfigure
rqt_plot /wheel/odom_raw/twist/twist/linear/x
```

在 rqt 中选择 `/small_car_base`。修改一项数值后按 Enter；数值保持不变表示 MCU
写入并回读成功。每次只改一项。

通过标准：

- [ ] ROS 节点、里程计、IMU 和诊断均正常。
- [ ] 已准备物理急停方式，测试区域安全。

## 1. 电机方向与最小驱动

先将小车架起，确认四轮方向正确，再放回地面测试。低速前进 3 秒：

```bash
ros2 topic pub --wait-matching-subscriptions 1 -r 20 -t 60 /cmd_vel_nav \
  geometry_msgs/msg/TwistStamped \
  "{header: auto, twist: {linear: {x: 0.10}, angular: {z: 0.0}}}"
```

`-t 60` 表示在 DDS 匹配完成后发送 60 条消息，即实际控制 3 秒。不要使用
`timeout 3`，因为它会把节点启动和 DDS 发现时间也计入 3 秒，导致实际控制时间不足。
命令结束后 MCU 会在 500 ms 内超时停车。四轮必须同向，且
`/wheel/odom_raw.twist.twist.linear.x` 为正。可在树莓派 ROS 容器内自动搜索正反向
起转阈值：

```bash
python3 /workspace/smart_car/robot_host/scripts/calibrate_wheel_pwm.py \
  --confirm-wheels-off-ground
```

脚本会暂停 Nav2、搜索阈值、复测并恢复原运行参数。当前架空实测最低通过值为
560，配置使用带 20 裕量的 `wheel_pwm_min=580`。若结果明显升高，不要用过大的
PWM 掩盖供电不足或机械卡滞。

四轮着地原地转向需要额外克服轮胎侧向静摩擦。实测 `580` 和 `650` 均无法
起转，`750` 可以产生方向正确的左右轮速，因此使用
`wheel_turn_start_pwm=750`。该值只在左右轮目标反向且编码器仍静止时触发，
保持约 250 ms 后恢复 `wheel_pwm_min`，不会持续放大 Nav2 的低角速度命令。

通过标准：

- [*] 四轮目视方向正确，停止命令后不继续转动。
- [ ] 连续测试 5 次均能低速启动，无明显抖动或卡滞。

## 2. 直线距离比例

使用胶带标出 2～3 m 直线。以 0.20 m/s 行驶，记录 `/odom` 起点和终点位置，
同时用卷尺测量车体中心的真实距离。可用以下命令查看当前位置：

```bash
ros2 topic echo /odom --once

# 开始低速直行；车体中心到达终点标线时按 Ctrl+C，随后看门狗自动停车。
ros2 topic pub --wait-matching-subscriptions 1 -r 20 /cmd_vel_nav geometry_msgs/msg/TwistStamped \
  "{header: auto, twist: {linear: {x: 0.20}, angular: {z: 0.0}}}"
```

计算：

```text
新 odom_mm_per_tick_num
  = 当前值 × 真实距离 ÷ ROS测量距离
```

例如当前值 2513，真实距离 2.000 m，ROS 测得 1.960 m：

```text
2513 × 2.000 ÷ 1.960 ≈ 2564
```

在 rqt 修改 `odom_mm_per_tick_num`，按 Enter 后重复测试。分别完成正向 3 次、
反向 3 次，取结果平均值。不要用“速度 × 时间”代替卷尺距离，因为加减速阶段会
引入误差。

通过标准：

- [ ] 正向和反向的平均距离误差均小于 2%。
- [ ] 六次计算结果接近，没有某次明显跳变。

## 3. 左右轮直线一致性

当前 MCU 使用左右两组闭环：A/B 共用左侧输出，C/D 共用右侧输出；同侧两个编码器
先取平均。`/joint_states` 当前也复制左右平均速度，不能据此证明四个电机逐个同步。
架空时可检查左右轮组的基础一致性：

```bash
python3 /workspace/smart_car/robot_host/scripts/calibrate_wheel_balance.py
```

当前架空正反向差异均小于 2%，因此保持
`wheel_left_output_permille=1000`、`wheel_right_output_permille=1000`。最终补偿仍以
落地直线结果为准，不为小于 2% 的空载差异强行补偿。

保持 `angular.z=0`，沿 2～3 m 标线行驶。车头向左偏说明左侧相对偏慢，可增加
`wheel_left_output_permille` 或减小 `wheel_right_output_permille`；向右偏则反向
调整。每次只调整一侧 5～20，并重新测试正向和反向。

调整示例：

```bash
ros2 param set --no-daemon --spin-time 4 --timeout 5 \
  /small_car_base wheel_left_output_permille 1010
```

通过标准：

- [*] 直行 2 m 的横向偏差不超过 3 cm。
- [ ] 正向和反向没有明显相反的严重偏移。

## 4. 原地旋转与有效轮距

在车体和地面做方向标记，以 0.5 rad/s 分别顺、逆时针旋转 3～5 圈。使用 RViz
或 `tf2_echo` 观察融合里程计角度：

```bash
ros2 run tf2_ros tf2_echo odom base_link
#Rotation: in RPY (radian) 弧度
#Rotation: in RPY (degree) 角度

# 逆时针旋转；达到计划圈数时按 Ctrl+C，随后看门狗自动停车。
ros2 topic pub --wait-matching-subscriptions 1 -r 20 /cmd_vel_nav geometry_msgs/msg/TwistStamped \
  "{header: auto, twist: {linear: {x: 0.0}, angular: {z: 0.5}}}"
```

顺时针测试时把 `angular.z` 改为 `-0.5`。

计算有效轮距：

```text
新 wheel_track_mm
  = 当前值 × ROS旋转角度 ÷ 真实旋转角度
```

例如当前轮距 115 mm，实际旋转 1800°，ROS 显示 1900°：

```text
115 × 1900 ÷ 1800 ≈ 121 mm
```

在 rqt 修改 `wheel_track_mm` 后重复测试。顺、逆时针结果差异较大时，先返回阶段
3 检查左右轮补偿和机械阻力，不要用轮距同时补偿两种误差。

通过标准：

- [ ] 单圈误差不超过 3°，多圈累计误差不超过 2%。
- [ ] 顺、逆时针标定值接近，原地旋转时平移漂移较小。

## 5. IMU 检查

车身静止时可自动采集 20 秒 IMU 数据：

```bash
python3 /workspace/smart_car/robot_host/scripts/calibrate_imu_static.py
```

两轮架空静止采样得到的保守配置为 `imu_acceleration_variance=0.018`、
`imu_angular_velocity_variance=0.003`。这两个参数位于 `config/base.yaml`，修改后需要
重启 ROS 节点。横滚和俯仰偏置只有在车身处于已知水平面时才能标定，不能把支架
倾斜写入偏置。

小车静止 60 秒，观察：

```bash
rqt_plot /imu/data_raw/angular_velocity/z
```

静止值应围绕 0 小幅波动。`gyro_lsb_per_dps_x10` 是角速度比例，只有在使用可靠
外部角度基准并对角速度积分后才调整，不能用它消除静止零偏。

当前系统没有独立的 Z 轴陀螺仪零偏参数。如果静止时长期明显偏离 0，先停止
Nav2 验收并增加零偏补偿；不要通过修改 `wheel_track_mm` 掩盖 IMU 漂移。

通过标准：

- [ ] 静止时 `/odom` 航向不会持续明显旋转。
- [ ] 缓慢旋转一圈时，IMU 与轮式旋转方向一致。

## 6. 轮速闭环与加速度

依次测试 0.15、0.30、0.50 m/s。先调 `wheel_speed_kp_x100`，使实际速度快速
接近目标；再小幅增加 `wheel_speed_ki_x100` 消除稳态误差。出现持续振荡或声音
周期变化时降低 Kp 或 Ki。`wheel_accel_limit_mm_s2` 初始建议 300～500。

角速度依次测试 0.5、1.0 rad/s。线速度和角速度上限由
`max_linear_speed_mm_s`、`max_angular_speed_mrad_s` 控制。初次 Nav2 联调建议限制
为 300 mm/s 和 1000 mrad/s。

通过标准：

- [ ] 三档稳定线速度误差均小于 5%。
- [ ] 加减速平顺，无持续振荡、打滑或明显超调。
- [ ] 松开控制或停止发布后，500 ms 内可靠停车。

## 7. Nav2 验收

完成以下测试并在 RViz 观察 `odom -> base_link` 连续性：

1. 目标直行 1 m、2 m。
2. 原地旋转 90°、180°、360°。
3. 行驶边长 1 m 的正方形并回到起点。
4. 静止 2 分钟，检查位置和航向漂移。

Nav2 不靠固定时间控制距离，而是持续根据 `/odom` 和 TF 的目标误差输出
`/cmd_vel`。因此距离比例、轮距和静止漂移必须先通过，才能继续调 Nav2 控制器。

建议验收目标：

- [ ] 2 m 直线距离误差小于 4 cm。
- [ ] 360° 旋转误差小于 3°。
- [ ] 1 m 正方形结束后位置误差小于 10 cm。
- [ ] Nav2 制动稳定，没有明显来回修正或终点振荡。

## 8. 保存结果

rqt 修改只在当前运行期间有效。每完成一个阶段，立即把最终值写回
`ros/small_car_base/config/chassis.yaml`，然后重启 ROS，确认参数仍正确。

| 阶段 | 参数 | 初始值 | 最终值 | 测试结果 |
| --- | --- | --- | --- | --- |
| 最小驱动 | `wheel_pwm_min` | 550 | 580 | 架空正反向复测通过 |
| 原地转向起步 | `wheel_turn_start_pwm` | 无 | 750 | 四轮着地、`angular.z=0.5` 起转通过 |
| 距离 | `odom_mm_per_tick_num` | 2513 | 2166 | 实际 2.000 m，ROS 位移 1.9996 m |
| 直线 | 左右输出补偿 | 1000/1000 | 1000/1000 | 架空差异小于 2%，落地 2 m 偏差可忽略 |
| 旋转 | `wheel_track_mm` | | | |
| IMU 噪声 | 加速度/角速度方差 | 0.1/0.02 | 0.018/0.003 | 两轮静止采样 |
| IMU 比例 | `gyro_lsb_per_dps_x10` | 164 | 待定 | 需要外部角度基准 |
| 闭环 | Kp、Ki、加速度 | | | |

所有阶段通过后再提高 Nav2 最大速度；每次提高后重新执行直线、旋转和急停测试。
