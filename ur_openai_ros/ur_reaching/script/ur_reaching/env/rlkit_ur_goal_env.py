'''
    By Geonhee Lee <gunhee6392@gmail.com>
    Refer to https://github.com/openai/gym/blob/master/docs/creating-environments.md
'''
# Python
import copy
import numpy as np
import math
import sys
import time

# ROS 
import rospy
#import tf
from .joint_publisher import JointPub
from .joint_traj_publisher import JointTrajPub

# Gazebo
from gazebo_msgs.srv import SetModelState, SetModelStateRequest, GetModelState
from gazebo_msgs.srv import GetWorldProperties
from gazebo_msgs.msg import LinkStates 

# For reset GAZEBO simultor
from .gazebo_connection import GazeboConnection
from .controllers_connection import ControllersConnection

# ROS msg
from geometry_msgs.msg import Pose, Point, Quaternion, Vector3
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from std_srvs.srv import SetBool, SetBoolResponse, SetBoolRequest
from std_srvs.srv import Empty

# Gym
import gym
from gym import error, spaces, utils
from gym.utils import seeding
# For register my env
from gym.envs.registration import register
from collections import OrderedDict

# For inherit RobotGazeboEnv
from ur_reaching.env import robot_gazebo_env_goal

# UR5 Utils
from ur_reaching.env.ur_setups import setups
from ur_reaching.env import ur_utils

# ROS
import rospy
import rospkg

#register the training environment in the gym as an available one
reg = gym.envs.register(
    id='RLkitGoalUR-v0',
    entry_point='ur_reaching.env:RLkitGoalUR', # Its directory associated with importing in other sources like from 'ur_reaching.env.ur_sim_env import *' 
    #timestep_limit=100000,
    )

class RLkitGoalUR(robot_gazebo_env_goal.RobotGazeboEnv):
    
    def __init__(self):    
        self._ros_init()

        # For RLkit and gym     
        self.goal_oriented = True

        if self.goal_oriented is False :
            self.obs_space_low = np.array(
                [self.joint_limits["shp_min"], self.joint_limits["shl_min"], self.joint_limits["elb_min"], \
                self.joint_limits["wr1_min"], self.joint_limits["wr2_min"], self.joint_limits["wr3_min"], \
                self.joint_velocty_limits["shp_vel_min"], self.joint_velocty_limits["shl_vel_min"], self.joint_velocty_limits["elb_vel_min"], \
                self.joint_velocty_limits["wr1_vel_min"],  self.joint_velocty_limits["wr2_vel_min"],  self.joint_velocty_limits["wr3_vel_min"], \
                self.xyz_limits["x_min"],  self.xyz_limits["y_min"],  self.xyz_limits["z_min"]])
            self.obs_space_high = np.array(
                [self.joint_limits["shp_max"], self.joint_limits["shl_max"], self.joint_limits["elb_max"], \
                self.joint_limits["wr1_max"], self.joint_limits["wr2_max"], self.joint_limits["wr3_max"], \
                self.joint_velocty_limits["shp_vel_max"], self.joint_velocty_limits["shl_vel_max"], self.joint_velocty_limits["elb_vel_max"], \
                self.joint_velocty_limits["wr1_vel_max"],  self.joint_velocty_limits["wr2_vel_max"],  self.joint_velocty_limits["wr3_vel_max"],  \
                self.xyz_limits["x_max"],  self.xyz_limits["y_max"],  self.xyz_limits["z_max"]])
            observation_space = spaces.Box(
                low=self.obs_space_low, \
                high=self.obs_space_high, \
                dtype=np.float32)
            self.observation_space = observation_space
        else:
            self.obs_space_low = np.array(
                [self.joint_limits["shp_min"], self.joint_limits["shl_min"], self.joint_limits["elb_min"], \
                self.joint_limits["wr1_min"], self.joint_limits["wr2_min"], self.joint_limits["wr3_min"]])
            self.obs_space_high = np.array(
                [self.joint_limits["shp_max"], self.joint_limits["shl_max"], self.joint_limits["elb_max"], \
                self.joint_limits["wr1_max"], self.joint_limits["wr2_max"], self.joint_limits["wr3_max"]])
            observation_space = spaces.Box(
                low=self.obs_space_low, \
                high=self.obs_space_high, \
                dtype=np.float32)
            self.observation_space = observation_space
            self.observation_space = spaces.Dict(dict(
                desired_goal=spaces.Box(
                    low=np.array([self.xyz_limits["x_min"],  self.xyz_limits["y_min"],  self.xyz_limits["z_min"]]), \
                    high=np.array([self.xyz_limits["x_max"],  self.xyz_limits["y_max"],  self.xyz_limits["z_max"]]), \
                    dtype=np.float32),
                achieved_goal=spaces.Box(
                    low=np.array([self.xyz_limits["x_min"],  self.xyz_limits["y_min"],  self.xyz_limits["z_min"]]), \
                    high=np.array([self.xyz_limits["x_max"],  self.xyz_limits["y_max"],  self.xyz_limits["z_max"]]), \
                    dtype=np.float32),
                observation=self.observation_space
            ))
                
        action_space = spaces.Box(
            low=np.array(
                [self.joint_velocty_limits["shp_vel_min"], self.joint_velocty_limits["shl_vel_min"], \
                self.joint_velocty_limits["elb_vel_min"], self.joint_velocty_limits["wr1_vel_min"],  \
                self.joint_velocty_limits["wr2_vel_min"],  self.joint_velocty_limits["wr3_vel_min"]]), \
            high=np.array([
                self.joint_velocty_limits["shp_vel_max"], self.joint_velocty_limits["shl_vel_max"], \
                self.joint_velocty_limits["elb_vel_max"], self.joint_velocty_limits["wr1_vel_max"],  \
                self.joint_velocty_limits["wr2_vel_max"],  self.joint_velocty_limits["wr3_vel_max"]]), \
                dtype=np.float32)
        self.action_space = action_space
        self.current_pos = None
        #self.goal = np.array([-.14, -.13, 0.26])
        self.set_goal(self.sample_goal_for_rollout())

        # Gym interface and action
        self.reward_range = (-np.inf, np.inf)
        self._seed()
        metadata = {'render.modes': ['human']}
        spec = None

    def _ros_init(self):
        # Can check log msgs according to log_level {rospy.DEBUG, rospy.INFO, rospy.WARN, rospy.ERROR} 
        rospy.init_node('RLkitGoalUR', anonymous=True, log_level=rospy.INFO)
        rospy.logdebug("Starting RLkitGoalUR Class object...")

        # Init GAZEBO Objects
        self.set_obj_state = rospy.ServiceProxy('/gazebo/set_model_state', SetModelState)
        self.get_world_state = rospy.ServiceProxy('/gazebo/get_world_properties', GetWorldProperties)

        # Subscribe joint state and target pose
        rospy.Subscriber("/joint_states", JointState, self.joints_state_callback)
        rospy.Subscriber("/target_blocks_pose", Point, self.target_point_callback)
        rospy.Subscriber("/gazebo/link_states", LinkStates, self.link_state_callback)

        # Gets training parameters from param server
        self.desired_pose = Pose()
        self.running_step = rospy.get_param("/running_step")
        self.max_height = rospy.get_param("/max_height")
        self.min_height = rospy.get_param("/min_height")
        self.observations = rospy.get_param("/observations")
        
        # Joint limitation
        shp_max = rospy.get_param("/joint_limits_array/shp_max")
        shp_min = rospy.get_param("/joint_limits_array/shp_min")
        shl_max = rospy.get_param("/joint_limits_array/shl_max")
        shl_min = rospy.get_param("/joint_limits_array/shl_min")
        elb_max = rospy.get_param("/joint_limits_array/elb_max")
        elb_min = rospy.get_param("/joint_limits_array/elb_min")
        wr1_max = rospy.get_param("/joint_limits_array/wr1_max")
        wr1_min = rospy.get_param("/joint_limits_array/wr1_min")
        wr2_max = rospy.get_param("/joint_limits_array/wr2_max")
        wr2_min = rospy.get_param("/joint_limits_array/wr2_min")
        wr3_max = rospy.get_param("/joint_limits_array/wr3_max")
        wr3_min = rospy.get_param("/joint_limits_array/wr3_min")
        self.joint_limits = {"shp_max": shp_max,
                             "shp_min": shp_min,
                             "shl_max": shl_max,
                             "shl_min": shl_min,
                             "elb_max": elb_max,
                             "elb_min": elb_min,
                             "wr1_max": wr1_max,
                             "wr1_min": wr1_min,
                             "wr2_max": wr2_max,
                             "wr2_min": wr2_min,
                             "wr3_max": wr3_max,
                             "wr3_min": wr3_min
                             }

        # Joint Velocity limitation
        shp_vel_max = rospy.get_param("/joint_velocity_limits_array/shp_max")
        shp_vel_min = rospy.get_param("/joint_velocity_limits_array/shp_min")
        shl_vel_max = rospy.get_param("/joint_velocity_limits_array/shl_max")
        shl_vel_min = rospy.get_param("/joint_velocity_limits_array/shl_min")
        elb_vel_max = rospy.get_param("/joint_velocity_limits_array/elb_max")
        elb_vel_min = rospy.get_param("/joint_velocity_limits_array/elb_min")
        wr1_vel_max = rospy.get_param("/joint_velocity_limits_array/wr1_max")
        wr1_vel_min = rospy.get_param("/joint_velocity_limits_array/wr1_min")
        wr2_vel_max = rospy.get_param("/joint_velocity_limits_array/wr2_max")
        wr2_vel_min = rospy.get_param("/joint_velocity_limits_array/wr2_min")
        wr3_vel_max = rospy.get_param("/joint_velocity_limits_array/wr3_max")
        wr3_vel_min = rospy.get_param("/joint_velocity_limits_array/wr3_min")
        self.joint_velocty_limits = {"shp_vel_max": shp_vel_max,
                             "shp_vel_min": shp_vel_min,
                             "shl_vel_max": shl_vel_max,
                             "shl_vel_min": shl_vel_min,
                             "elb_vel_max": elb_vel_max,
                             "elb_vel_min": elb_vel_min,
                             "wr1_vel_max": wr1_vel_max,
                             "wr1_vel_min": wr1_vel_min,
                             "wr2_vel_max": wr2_vel_max,
                             "wr2_vel_min": wr2_vel_min,
                             "wr3_vel_max": wr3_vel_max,
                             "wr3_vel_min": wr3_vel_min
                             }

        #  Init joint pose
        shp_init_value = rospy.get_param("/init_joint_pose/shp")
        shl_init_value = rospy.get_param("/init_joint_pose/shl")
        elb_init_value = rospy.get_param("/init_joint_pose/elb")
        wr1_init_value = rospy.get_param("/init_joint_pose/wr1")
        wr2_init_value = rospy.get_param("/init_joint_pose/wr2")
        wr3_init_value = rospy.get_param("/init_joint_pose/wr3")
        self.init_joint_pose = [shp_init_value, shl_init_value, elb_init_value, wr1_init_value, wr2_init_value, wr3_init_value]

        # 3D coordinate limits
        x_max = rospy.get_param("/cartesian_limits/x_max")
        x_min = rospy.get_param("/cartesian_limits/x_min")
        y_max = rospy.get_param("/cartesian_limits/y_max")
        y_min = rospy.get_param("/cartesian_limits/y_min")
        z_max = rospy.get_param("/cartesian_limits/z_max")
        z_min = rospy.get_param("/cartesian_limits/z_min")       
        self.xyz_limits = {"x_max": x_max,
                            "x_min": shp_vel_min,
                            "y_max": y_max,
                            "y_min": y_min,
                            "z_max": z_max,
                            "z_min": z_min
                            }

        # Fill in the Done Episode Criteria list
        self.episode_done_criteria = rospy.get_param("/episode_done_criteria")
        
        # Stablishes connection with simulator
        self._gz_conn = GazeboConnection()
        self._ctrl_conn = ControllersConnection(namespace="")
        
        # Controller type for ros_control
        self._ctrl_type =  rospy.get_param("/control_type")
        self.pre_ctrl_type =  self._ctrl_type

        # Init the observations, target, ...
        self.base_orientation = Quaternion()
        self.target_point = Point()
        self.link_state = LinkStates()
        self.joints_state = JointState()
        self.end_effector = Point() 
        self.distance = 0.

        # Arm/Control parameters
        self._ik_params = setups['UR5_6dof']['ik_params']
        
        # ROS msg type
        self._joint_pubisher = JointPub()
        self._joint_traj_pubisher = JointTrajPub()

        # Controller list
        self.vel_traj_controller = ['joint_state_controller',
                            'gripper_controller',
                            'vel_traj_controller']
        self.vel_controller = ["joint_state_controller",
                                "gripper_controller",
                                "ur_shoulder_pan_vel_controller",
                                "ur_shoulder_lift_vel_controller",
                                "ur_elbow_vel_controller",
                                "ur_wrist_1_vel_controller",
                                "ur_wrist_2_vel_controller",
                                "ur_wrist_3_vel_controller"]

        # Stop flag durning training 
        self.stop_flag = False
    
    def _start_ros_services(self):
        stop_trainning_server = rospy.Service('/stop_training', SetBool, self._stop_trainnig)
        start_trainning_server = rospy.Service('/start_training', SetBool, self._start_trainnig)

        # Change the controller type 
        set_joint_vel_server = rospy.Service('/set_velocity_controller', SetBool, self._set_vel_ctrl)
        set_joint_traj_vel_server = rospy.Service('/set_trajectory_velocity_controller', SetBool, self._set_traj_vel_ctrl)

        return self

    def step(self, action):
        """

        Parameters
        ----------
        action : [change in x, change in y, change in z]

        Returns
        -------
        ob, reward, episode_over, info : tuple
            ob (object) :
                either current position or an observation object, depending on
                the type of environment this is representing
            reward (float) :
                negative, squared, l2 distance between current position and 
                goal position
            episode_over (bool) :
                Whether or not we have reached the goal
            info (dict) :
                 For now, all this does is keep track of the total distance from goal.
                 This is used for rlkit to get the final total distance after evaluation.
                 See function get_diagnostics for more info.
        """
        rospy.logdebug("### UR step func ###")

        self.training_ok()

        # Given the action selected by the learning algorithm,
        # we perform the corresponding movement of the robot

        # Act
        self._gz_conn.unpauseSim()
        self.act(action)
        
        # Then we send the command to the robot and let it go
        # for running_step seconds
        time.sleep(self.running_step)
        self._gz_conn.pauseSim()

        # We now process the latest data saved in the class state to calculate
        # the state and the rewards. This way we guarantee that they work
        # with the same exact data.
        # Generate State based on observations

        # finally we get an evaluation based on what happened in the sim

        #return observation, reward, done, {}
        return self._generate_step_tuple()

    # Resets the state of the environment and returns an initial observation.
    def reset(self):
        # 0st: We pause the Simulator
        rospy.logdebug("Pausing SIM...")
        self._gz_conn.pauseSim()

        # 1st: resets the simulation to initial values
        rospy.logdebug("Reset SIM...")
        self._gz_conn.resetSim()

        # 2nd: We Set the gravity to 0.0 so that we dont fall when reseting joints
        # It also UNPAUSES the simulation
        rospy.logdebug("Remove Gravity...")
        self._gz_conn.change_gravity_zero()

        # EXTRA: Reset JoinStateControlers because sim reset doesnt reset TFs, generating time problems
        rospy.logdebug("reset_ur_joint_controllers...")
        self._ctrl_conn.reset_ur_joint_controllers(self._ctrl_type)

        # 3rd: resets the robot to initial conditions
        rospy.logdebug("set_init_pose init variable...>>>" + str(self.init_joint_pose))
        # We save that position as the current joint desired position
        init_pos = self.init_joints_pose(self.init_joint_pose)

        # 4th: We Set the init pose to the jump topic so that the jump control can update
        # We check the jump publisher has connection

        if self._ctrl_type == 'traj_vel':
            self._joint_traj_pubisher.check_publishers_connection()
        elif self._ctrl_type == 'vel':
            self._joint_pubisher.check_publishers_connection()
        else:
            rospy.logwarn("Controller type is wrong!!!!")
        

        # 5th: Check all subscribers work.
        # Get the state of the Robot defined by its RPY orientation, distance from
        # desired point, contact force and JointState of the three joints
        rospy.logdebug("check_all_systems_ready...")
        self.check_all_systems_ready()

        # 6th: We restore the gravity to original
        rospy.logdebug("Restore Gravity...")
        self._gz_conn.adjust_gravity()

        # 7th: pauses simulation
        rospy.logdebug("Pause SIM...")
        self._gz_conn.pauseSim()
        # self._init_obj_pose()

        # 8th: Get the State Discrete Stringuified version of the observations
        rospy.logdebug("get_observations...")
        observation = self.get_observations()

        if self.goal_oriented:
            self.set_goal(self.sample_goal_for_rollout())
            return self._get_obs()
            
        return observation
    
    def act(self, action):
        if self._ctrl_type == 'traj_vel':
            self.pre_ctrl_type = 'traj_vel'
            self._joint_traj_pubisher.jointTrajectoryCommand(action)
        elif self._ctrl_type == 'vel':
            self.pre_ctrl_type = 'vel'
            self._joint_pubisher.move_joints(action)
        else:
            self._joint_pubisher.move_joints(action)

    def render(self, mode='human', close=False):
        pass

    def check_stop_flg(self):
        if self.stop_flag is False:
            return False
        else:
            return True

    def _start_trainnig(self, req):
        rospy.logdebug("_start_trainnig!!!!")
        self.stop_flag = False
        return SetBoolResponse(True, "_start_trainnig")

    def _stop_trainnig(self, req):
        rospy.logdebug("_stop_trainnig!!!!")
        self.stop_flag = True
        return SetBoolResponse(True, "_stop_trainnig")

    def _set_vel_ctrl(self, req):
        rospy.wait_for_service('set_velocity_controller')
        self._ctrl_conn.stop_controllers(self.vel_traj_controller)
        self._ctrl_conn.start_controllers(self.vel_controller)
        self._ctrl_type = 'vel'
        return SetBoolResponse(True, "_set_vel_ctrl")

    def _set_traj_vel_ctrl(self, req):
        rospy.wait_for_service('set_trajectory_velocity_controller')
        self._ctrl_conn.stop_controllers(self.vel_controller)
        self._ctrl_conn.start_controllers(self.vel_traj_controller)    
        self._ctrl_type = 'traj_vel'
        return SetBoolResponse(True, "_set_traj_vel_ctrl")  

    # A function to initialize the random generator
    def _seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]
        
    def link_state_callback(self, msg):
        self.link_state = msg
        self.end_effector = self.link_state.pose[8]
        self.current_eef = np.array([self.end_effector.position.x, self.end_effector.position.y, self.end_effector.position.z], dtype=np.float32)
            
    def target_point_callback(self, msg):
        self.target_point = msg

    def check_all_systems_ready(self):
        """
        We check that all systems are ready
        :return:
        """
        joint_states_msg = None
        while joint_states_msg is None and not rospy.is_shutdown():
            try:
                joint_states_msg = rospy.wait_for_message("/joint_states", JointState, timeout=0.1)
                self.joints_state = joint_states_msg
                rospy.logdebug("Current joint_states READY")
            except Exception as e:
                #self._ctrl_conn.load_controllers("joint_state_controller")
                self._ctrl_conn.start_controllers(controllers_on="joint_state_controller")                
                rospy.logdebug("Current joint_states not ready yet, retrying==>"+str(e))
        
        target_pose_msg = None
        while target_pose_msg is None and not rospy.is_shutdown():
            try:
                target_pose_msg = rospy.wait_for_message("/target_blocks_pose", Point, timeout=0.1)
                self.target_point = target_pose_msg
                rospy.logdebug("Reading target pose READY")
            except Exception as e:
                rospy.logdebug("Reading target pose not ready yet, retrying==>"+str(e))

        rospy.logdebug("ALL SYSTEMS READY")

    def get_orientation(self, q):
        """Get Euler angles 
        Args:
            q: a numpy array of joints angle positions.
        Returns:
            xyz are the x,y,z coordinates of an end-effector in a Cartesian space.
        """
        mat = ur_utils.forward(q, self._ik_params)
        orientation = mat[0:3, 0:3]
        roll = -orientation[1, 2]
        pitch = orientation[0, 2]
        yaw = -orientation[0, 1]
        
        return Vector3(roll, pitch, yaw)

    def init_joints_pose(self, init_pos):
        """
        We initialise the Position variable that saves the desired position where we want our
        joints to be
        :param init_pos:
        :return:
        """
        self.current_joint_pose =[]
        self.current_joint_pose = copy.deepcopy(init_pos)
        return self.current_joint_pose

    def joints_state_callback(self,msg):
        self.joints_state = msg

    def _get_current_joint_positions(self):
        joint_states = self.joints_state
        shp_joint_ang = joint_states.position[0]
        shl_joint_ang = joint_states.position[1]
        elb_joint_ang = joint_states.position[2]
        wr1_joint_ang = joint_states.position[3]
        wr2_joint_ang = joint_states.position[4]
        wr3_joint_ang = joint_states.position[5]

        observation = []
        for obs_name in self.observations:
            if obs_name == "shp_joint_ang":
                observation.append(shp_joint_ang)
            elif obs_name == "shl_joint_ang":
                observation.append(shl_joint_ang)
            elif obs_name == "elb_joint_ang":
                observation.append(elb_joint_ang)
            elif obs_name == "wr1_joint_ang":
                observation.append(wr1_joint_ang)
            elif obs_name == "wr2_joint_ang":
                observation.append(wr2_joint_ang)
            elif obs_name == "wr3_joint_ang":
                observation.append(wr3_joint_ang)

        return np.array(observation, dtype=np.float32)

    def _get_current_joint_velocities(self):
        joint_states = self.joints_state
        shp_joint_vel = joint_states.velocity[0]
        shl_joint_vel = joint_states.velocity[1]
        elb_joint_vel = joint_states.velocity[2]
        wr1_joint_vel = joint_states.velocity[3]
        wr2_joint_vel = joint_states.velocity[4]
        wr3_joint_vel = joint_states.velocity[5]

        observation = []
        for obs_name in self.observations:
            if obs_name == "shp_joint_vel":
                observation.append(shp_joint_vel)
            elif obs_name == "shl_joint_vel":
                observation.append(shl_joint_vel)
            elif obs_name == "elb_joint_vel":
                observation.append(elb_joint_vel)
            elif obs_name == "wr1_joint_vel":
                observation.append(wr1_joint_vel)
            elif obs_name == "wr2_joint_vel":
                observation.append(wr2_joint_vel)
            elif obs_name == "wr3_joint_vel":
                observation.append(wr3_joint_vel)
        return np.array(observation, dtype=np.float32)

    def _get_current_end_effector_position(self):
        return self.current_eef

    def get_observations(self):
        """
        Returns the state of the robot needed for OpenAI QLearn Algorithm
        The state will be defined by an array
        :return: observation
        """
        rospy.logdebug("joint_positions==>"+str(self._get_current_joint_positions()))
        rospy.logdebug("joint_velocities==>"+str(self._get_current_joint_velocities()))
        rospy.logdebug("current_end_effector_position==>"+str(self._get_current_end_effector_position()))

        return np.concatenate(
                [self._get_current_joint_positions(),
                self._get_current_joint_velocities(),
                self._get_current_end_effector_position()],
                axis = 0)

    def clamp_to_joint_limits(self):
        """
        clamps self.current_joint_pose based on the joint limits
        self._joint_limits
        {
         "shp_max": shp_max,
         "shp_min": shp_min,
         ...
         }
        :return:
        """

        rospy.logdebug("Clamping current_joint_pose>>>" + str(self.current_joint_pose))
        shp_joint_value = self.current_joint_pose[0]
        shl_joint_value = self.current_joint_pose[1]
        elb_joint_value = self.current_joint_pose[2]
        wr1_joint_value = self.current_joint_pose[3]
        wr2_joint_value = self.current_joint_pose[4]
        wr3_joint_value = self.current_joint_pose[5]

        self.current_joint_pose[0] = max(min(shp_joint_value, self._joint_limits["shp_max"]),
                                         self._joint_limits["shp_min"])
        self.current_joint_pose[1] = max(min(shl_joint_value, self._joint_limits["shl_max"]),
                                         self._joint_limits["shl_min"])
        self.current_joint_pose[2] = max(min(elb_joint_value, self._joint_limits["elb_max"]),
                                         self._joint_limits["elb_min"])
        self.current_joint_pose[3] = max(min(wr1_joint_value, self._joint_limits["wr1_max"]),
                                         self._joint_limits["wr1_min"])
        self.current_joint_pose[4] = max(min(wr2_joint_value, self._joint_limits["wr2_max"]),
                                         self._joint_limits["wr2_min"])
        self.current_joint_pose[5] = max(min(wr3_joint_value, self._joint_limits["wr3_max"]),
                                         self._joint_limits["wr3_min"])

        rospy.logdebug("DONE Clamping current_joint_pose>>>" + str(self.current_joint_pose))
        
    def training_ok(self):
        rate = rospy.Rate(1)
        while self.check_stop_flg() is True:                  
            rospy.logdebug("stop_flag is ON!!!!")
            self._gz_conn.unpauseSim()

            if self.check_stop_flg() is False:
                break 
            rate.sleep()
                    
    # For RLkit
    def sample_goal_for_rollout(self):
        return np.random.uniform(low=np.array([-.14, -.13, 0.26]), high=np.array([.14, .13, .39]))

    def set_goal(self, goal):
        print ("goal: ", goal)
        self.goal = goal

    def _generate_step_tuple(self):
        reward = self._get_reward(self.goal)

        episode_over = False
        total_distance_from_goal = np.sqrt(-reward)

        info = {}
        info['total_distance'] = total_distance_from_goal

        if reward > -0.0001:
            print ("Done, reward: ", reward)
            episode_over = True

        if self.goal_oriented:
            obs = self._get_obs()
            return obs, reward, episode_over, info

        #return self.current_pos, reward, episode_over, info        
        return self.get_observations(), reward, episode_over, info        

    def _get_reward(self, goal):
        return - (np.linalg.norm(self._get_current_end_effector_position() - goal) ** 2)

    # For HER
    def _get_obs(self):
        obs = {}
        obs['observation'] = self._get_current_joint_positions()
        obs['desired_goal'] = self.goal
        obs['achieved_goal'] = self._get_current_end_effector_position()
        return obs

    def compute_reward(self, achieved_goal, goal, info):
        return - (np.linalg.norm(achieved_goal - goal)**2)
    '''
    def get_diagnostics(self, paths):
        """
        This adds the diagnostic "Final Total Distance" for RLkit
        """
        def get_stat_in_paths(paths, dict_name, scalar_name):
            if len(paths) == 0:
                return np.array([[]])

            if type(paths[0][dict_name]) == dict:
                return [path[dict_name][scalar_name] for path in paths]
            return [[info[scalar_name] for info in path[dict_name]] for path in paths]

        def create_stats_ordered_dict(
                name,
                data,
                stat_prefix=None,
                always_show_all_stats=True,
                exclude_max_min=False,
        ):
            if stat_prefix is not None:
                name = "{} {}".format(stat_prefix, name)
            if isinstance(data, Number):
                return OrderedDict({name: data})

            if len(data) == 0:
                return OrderedDict()

            if isinstance(data, tuple):
                ordered_dict = OrderedDict()
                for number, d in enumerate(data):
                    sub_dict = create_stats_ordered_dict(
                        "{0}_{1}".format(name, number),
                        d,
                    )
                    ordered_dict.update(sub_dict)
                return ordered_dict

            if isinstance(data, list):
                try:
                    iter(data[0])
                except TypeError:
                    pass
                else:
                    data = np.concatenate(data)

            if (isinstance(data, np.ndarray) and data.size == 1
                    and not always_show_all_stats):
                return OrderedDict({name: float(data)})

            stats = OrderedDict([
                (name + ' Mean', np.mean(data)),
                (name + ' Std', np.std(data)),
            ])
            if not exclude_max_min:
                stats[name + ' Max'] = np.max(data)
                stats[name + ' Min'] = np.min(data)
            return stats
        statistics = OrderedDict()
        stat_name = 'total_distance'
        stat = get_stat_in_paths(paths, 'env_infos', stat_name)
        statistics.update(create_stats_ordered_dict('Final %s' % (stat_name), [
                          s[-1] for s in stat], always_show_all_stats=True,))
        return statistics
    '''
    
    # Functions for pickling and saving the state. Described in ProxyEnv of envs/wrappers.py  
    '''
        Refer to https://docs.python.org/3/library/pickle.html#pickle-protocol
    '''
    def __getstate__(self):
        state = self.__dict__.copy()
        del state['link_state']
        del state['base_orientation']
        del state['_joint_pubisher']
        del state['_joint_traj_pubisher']
        del state['distance']
        del state['joints_state']
        del state['get_world_state']
        del state['end_effector']
        del state['desired_pose']
        
        '''
        del state['_joint_pubisher']
        del state['_joint_traj_pubisher']
        del state['observations']
        del state['np_random']
        del state['distance']
        '''
        print ("rlkit_ur_env, __getstate__, state :", state)
        return state

    def __setstate__(self, state):
        self._ros_init()
        
        print ("##### rlkit_ur_env, __setstate__ :", state)
        self.__dict__.update(state)
        self.reset()
