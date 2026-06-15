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
bash scripts/test_smoke.sh      # быстрая проверка OpenVINS
bash scripts/test_tools.sh      # полная проверка окружения
```

Перед запуском скриптов с `source /opt/ros/...` не включайте `set -u` в той же shell-сессии — ROS setup использует неинициализированные переменные. Скрипты используют `scripts/lib.sh` для безопасного sourcing.

## EuRoC baseline / adaptive

```bash
python3 scripts/run_demo.py              # интерактивный demo
python3 scripts/run_demo.py --quick      # adaptive, MH_01, 60 с

bash scripts/run_euroc.sh baseline MH_01_easy --duration 60
bash scripts/run_euroc.sh adaptive MH_04_difficult --eval
```

Траектория: `datasets/results/.../trajectory_tum.txt` (TUM).  
Старые обёртки `run_euroc_baseline.sh` / `run_euroc_adaptive.sh` по-прежнему работают.

Старый сервер `robotics.ethz.ch` и Google Drive-зеркала OpenVINS часто недоступны.
По умолчанию используется официальный [ETH Research Collection](https://doi.org/10.3929/ethz-b-000690084).
