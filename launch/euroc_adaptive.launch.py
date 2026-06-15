from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import SetParameter
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    pkg_ov = get_package_share_directory("ov_msckf")
    subscribe_launch = os.path.join(pkg_ov, "launch", "subscribe.launch.py")

    return LaunchDescription([
        DeclareLaunchArgument("rviz_enable", default_value="false"),
        DeclareLaunchArgument("config", default_value="euroc_mav_trust"),
        DeclareLaunchArgument("config_path", default_value=""),
        DeclareLaunchArgument("verbosity", default_value="INFO"),
        SetParameter(name="use_sim_time", value=True),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(subscribe_launch),
            launch_arguments={
                "config": LaunchConfiguration("config"),
                "config_path": LaunchConfiguration("config_path"),
                "rviz_enable": LaunchConfiguration("rviz_enable"),
                "verbosity": LaunchConfiguration("verbosity"),
                "save_total_state": "false",
            }.items(),
        ),
    ])
