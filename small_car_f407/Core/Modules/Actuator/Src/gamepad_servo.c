/**
 * @file gamepad_servo.c
 * @brief 实现右摇杆对两自由度云台舵机的增量式控制。
 *
 * 摇杆回中后保持当前位置，不会自动把舵机复位到初始脉宽。
 */
#include "gamepad_servo.h"

/*
 * 手柄控制云台舵机模块。
 *
 * 当前策略是增量控制：右摇杆偏离中心时逐步改变舵机脉宽，
 * 摇杆松手后保持当前位置，而不是自动回中。
 */

#include <stdint.h>

#include "gamepad.h"
#include "servo.h"

#define GAMEPAD_SERVO_CENTER_VALUE 127
#define GAMEPAD_SERVO_MAX_VALUE 255
#define GAMEPAD_SERVO_DEADBAND 6
#define GAMEPAD_SERVO_MAX_STEP_US 30

static int16_t AxisDeviation(uint8_t axis)
{
  /* 计算摇杆相对中心点的偏移量。 */
  return (int16_t)axis - GAMEPAD_SERVO_CENTER_VALUE;
}

static int16_t AxisToStep(uint8_t axis)
{
  int16_t centered = AxisDeviation(axis);
  /* 摇杆回中时不改变舵机位置，实现“松手保持当前位置”。 */
  if ((centered > -GAMEPAD_SERVO_DEADBAND) && (centered < GAMEPAD_SERVO_DEADBAND))
  {
    return 0;
  }

  /* 偏移越大，舵机移动越快；最大每个调度周期变化 30us。 */
  return (int16_t)(((int32_t)centered * GAMEPAD_SERVO_MAX_STEP_US) /
                   (GAMEPAD_SERVO_MAX_VALUE - GAMEPAD_SERVO_CENTER_VALUE));
}

static uint16_t ClampMinPulse(int32_t pulse_us)
{
  if (pulse_us < (int32_t)SERVO_MIN_PULSE_US)
  {
    return SERVO_MIN_PULSE_US;
  }

  return (uint16_t)pulse_us;
}

static uint16_t ClampLeftPulse(int32_t pulse_us)
{
  /* left 舵机实测可以继续增大到 2300us。 */
  uint16_t clamped_pulse_us = ClampMinPulse(pulse_us);
  if (clamped_pulse_us > SERVO_LEFT_MAX_PULSE_US)
  {
    clamped_pulse_us = SERVO_LEFT_MAX_PULSE_US;
  }

  return clamped_pulse_us;
}

static uint16_t ClampRightPulse(int32_t pulse_us)
{
  /* right 舵机仍限制到 1700us，避免顶到机械限位。 */
  uint16_t clamped_pulse_us = ClampMinPulse(pulse_us);
  if (clamped_pulse_us > SERVO_RIGHT_MAX_PULSE_US)
  {
    clamped_pulse_us = SERVO_RIGHT_MAX_PULSE_US;
  }

  return clamped_pulse_us;
}

void GamepadServo_Init(void)
{
  /* 上电时两路舵机回到各自的安全初始位置。 */
  Servo_SetBothPulse(SERVO_LEFT_INIT_PULSE_US, SERVO_RIGHT_INIT_PULSE_US);
}

void GamepadServo_TaskStep(void)
{
  static uint16_t left_pulse_us = SERVO_LEFT_INIT_PULSE_US;
  static uint16_t right_pulse_us = SERVO_RIGHT_INIT_PULSE_US;
  GamepadState state;

  if (!Gamepad_GetState(&state))
  {
    /* 手柄未连接时不改舵机位置，保持最后一次有效位置。 */
    return;
  }

  /* 水平舵机的物理安装方向与右摇杆 X 轴相反。 */
  const int16_t left_step_us = (int16_t)-AxisToStep(state.rx);
  const int16_t right_step_us = AxisToStep(state.ry);
  if ((left_step_us == 0) && (right_step_us == 0))
  {
    /* 摇杆在死区内，不更新 PWM，也不产生串口日志。 */
    return;
  }

  left_pulse_us = ClampLeftPulse((int32_t)left_pulse_us + left_step_us);
  right_pulse_us = ClampRightPulse((int32_t)right_pulse_us + right_step_us);
  Servo_SetBothPulse(left_pulse_us, right_pulse_us);
}
