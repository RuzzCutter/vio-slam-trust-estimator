# vio-slam-trust-estimator

Адаптивная оценка достоверности визуальных измерений для VIO (OpenVINS).

- План: [`эксперимент_v2.txt`](эксперимент_v2.txt)
- Журнал: [`журнал_эксперимента.md`](журнал_эксперимента.md)

## Зависимости

Ubuntu 24.04, ROS 2 Jazzy, Ceres, OpenCV. См. `scripts/setup_env.sh`.

## Сборка

```bash
source /opt/ros/jazzy/setup.bash
cd ws_vins
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo
source install/setup.bash
```

## OpenVINS (форк)

Патч совместимости с ROS 2 Jazzy: ветка `jazzy/ros2-headers` в форке OpenVINS.
Файлы: `ov_msckf/src/ros/ROS2Visualizer.h`, `ROSVisualizerHelper.h`.

## Smoke-test

```bash
bash scripts/test_smoke.sh
```
