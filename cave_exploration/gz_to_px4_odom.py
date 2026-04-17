import os

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    RegisterEventHandler,
    TimerAction,
    SetEnvironmentVariable,
)
from launch.event_handlers import OnProcessExit, OnProcessStart
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, SetParameter


def generate_launch_description():
    px4_dir = LaunchConfiguration('px4_dir')
    model = LaunchConfiguration('model')
    world = LaunchConfiguration('world')
    model_pose = LaunchConfiguration('model_pose')
    sys_autostart = LaunchConfiguration('sys_autostart')

    # Apply sim time to every ROS node launched after this action.
    use_sim_time_global = SetParameter(name='use_sim_time', value=True)

    cleanup_stale_sim = ExecuteProcess(
        cmd=[
            'bash',
            '-lc',
            (
                "pkill -9 -f '^gz sim' || true; "
                "pkill -9 -f '^.*/px4_sitl_default/bin/px4($| )' || true; "
                "rm -f /tmp/px4_lock-* || true"
            ),
        ],
        output='screen',
    )

    # Gazebo -> ROS bridges
    #
    # Important:
    # - /clock is bridged one-way from Gazebo to ROS.
    # - /dynamic_pose/info is NOT bridged here because it is not a
    #   nav_msgs/Odometry topic. Bridge it properly only if you have a
    #   matching message type, or consume it directly with gz transport.
    bridge = Node(
        package='ros_gz_bridge',
        executable='parameter_bridge',
        name='ros_gz_bridge',
        arguments=[
            # Clock
            '/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock',

            # Front RGB camera
            '/rgb_camera@sensor_msgs/msg/Image@gz.msgs.Image',

            # Front depth camera
            '/depth_camera@sensor_msgs/msg/Image@gz.msgs.Image',
            '/depth_camera/points@sensor_msgs/msg/PointCloud2@gz.msgs.PointCloudPacked',
            '/camera_info@sensor_msgs/msg/CameraInfo@gz.msgs.CameraInfo',

            # IMU
            '/world/cave_simple_03/model/x500_depth_0/link/base_link/sensor/imu_sensor/imu'
            '@sensor_msgs/msg/Imu[gz.msgs.IMU',
        ],
        remappings=[
            ('/rgb_camera', '/drone/front_rgb'),
            ('/depth_camera', '/drone/front_depth'),
            ('/depth_camera/points', '/drone/front_depth/points'),
            ('/camera_info', '/drone/camera_info'),
            (
                '/world/cave_simple_03/model/x500_depth_0/link/base_link/sensor/imu_sensor/imu',
                '/drone/imu',
            ),
        ],
        output='screen',
    )

    # Optional node placeholder:
    # This is where your Gazebo-pose -> PX4 external odometry node should go.
    # Because use_sim_time is set globally above, it will also use sim time.
    #
    # odom_to_px4 = Node(
    #     package='your_package_name',
    #     executable='gz_pose_to_px4',
    #     name='gz_pose_to_px4',
    #     output='screen',
    # )

    start_px4 = ExecuteProcess(
        cmd=[
            'bash',
            '-lc',
            (
                'make px4_sitl '
                f'{model.perform(None) if False else ""}'
            )
        ],
        cwd=px4_dir,
        additional_env={
            'PX4_GZ_WORLD': world,
            'PX4_GZ_MODEL_POSE': model_pose,
            # Use a custom PX4 airframe/startup script here.
            # That script should set:
            # EKF2_MAG_TYPE=5
            # EKF2_GPS_CTRL=0
            # EKF2_HGT_REF=3
            # EKF2_EV_CTRL=11
            'PX4_SYS_AUTOSTART': sys_autostart,
        },
        # Simpler and more robust than trying to inject params from ROS launch.
        # PX4 startup scripts are the right place for EKF config.
        shell=True,
        output='screen',
    )

    # If you prefer not to rely on shell=True above, replace start_px4 with:
    #
    # start_px4 = ExecuteProcess(
    #     cmd=[
    #         'make',
    #         'px4_sitl',
    #         model,
    #         f'SYS_AUTOSTART:={sys_autostart}',
    #     ],
    #     cwd=px4_dir,
    #     additional_env={
    #         'PX4_GZ_WORLD': world,
    #         'PX4_GZ_MODEL_POSE': model_pose,
    #     },
    #     output='screen',
    # )
    #
    # Some setups are happier with the explicit SYS_AUTOSTART make argument.
    # If yours is, use that version instead.

    start_after_cleanup = RegisterEventHandler(
        OnProcessExit(
            target_action=cleanup_stale_sim,
            on_exit=[start_px4],
        )
    )

    start_bridge_after_px4 = RegisterEventHandler(
        OnProcessStart(
            target_action=start_px4,
            on_start=[
                TimerAction(
                    period=8.0,
                    actions=[
                        bridge,
                        # odom_to_px4,
                    ],
                )
            ],
        )
    )

    return LaunchDescription([
        DeclareLaunchArgument(
            'px4_dir',
            default_value=os.path.join(
                os.environ.get('HOME', f"/home/{os.environ.get('USER', 'user')}"),
                'PX4-Autopilot',
            ),
            description='Path to the PX4-Autopilot repository.',
        ),
        DeclareLaunchArgument(
            'model',
            default_value='gz_x500_depth',
            description='PX4 Gazebo model target passed to make px4_sitl.',
        ),
        DeclareLaunchArgument(
            'world',
            default_value='cave_simple_03',
            description='PX4 Gazebo world name (without .sdf).',
        ),
        DeclareLaunchArgument(
            'model_pose',
            default_value='0,0,2,0,0,1.57',
            description='PX4 spawn pose x,y,z,roll,pitch,yaw.',
        ),
        DeclareLaunchArgument(
            'sys_autostart',
            default_value='4001',
            description=(
                'PX4 SYS_AUTOSTART airframe ID. '
                'Set this to your custom airframe/startup script ID for cave flight.'
            ),
        ),

        # Global sim time for all ROS nodes
        use_sim_time_global,

        cleanup_stale_sim,
        start_after_cleanup,
        start_bridge_after_px4,
    ])