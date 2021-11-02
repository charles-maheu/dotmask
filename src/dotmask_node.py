#!/usr/bin/env python3
from __future__ import absolute_import
from __future__ import print_function

# General imports
import os
import rospy
import sys
import cv2
from cv_bridge import CvBridge, CvBridgeError
import numpy as np
import time
import scipy.io
from scipy.spatial.distance import cdist
import argparse
import matplotlib.pyplot as plt
from scipy import ndimage
import copy

# ROS
from sensor_msgs.msg import Image, CameraInfo
import std_msgs.msg
from std_msgs.msg import String
import tf
import roslib

# EKF
from kalmanFilter import extendedKalmanFilter

'''Uncomment for mask rcnn
 # Keras
import keras
from keras.models import Model
from keras import backend as K
K.common.set_image_dim_ordering('tf')

# Mask-RCNN
sys.path.append('../nn/Mask_RCNN/')
from mrcnn import config
from mrcnn import utils 
from mrcnn import model as modellib

class InferenceConfig(config.Config):
    NAME = "ISM mrcnn"
    GPU_COUNT = 1
    IMAGES_PER_GPU = 1
    NUM_CLASSES = 1 + 80
'''

def parse_args():
    parser = argparse.ArgumentParser(description='DOTmask - Real time masking for dynamic objects with depth-enabled cameras')
    parser.add_argument('--nn', action="store", default='yolact_edge', type=str,
                        help='Neural network to run ( mrcnn / yolact/ yolact++ / yolact_edge )', required=False)
    global args
    args = parser.parse_args(rospy.myargv()[4:])


def add_padding(img, pad_l, pad_t, pad_r, pad_b):
    height, width = img.shape
    #Adding padding to the left side.
    pad_left = np.zeros((height, pad_l), dtype = np.int)
    img = np.concatenate((pad_left, img), axis = 1)

    #Adding padding to the top.
    pad_up = np.zeros((pad_t, pad_l + width))
    img = np.concatenate((pad_up, img), axis = 0)

    #Adding padding to the right.
    pad_right = np.zeros((height + pad_t, pad_r))
    img = np.concatenate((img, pad_right), axis = 1)

    #Adding padding to the bottom
    pad_bottom = np.zeros((pad_b, pad_l + width + pad_r))
    img = np.concatenate((img, pad_bottom), axis = 0)

    return img

class DOTMask():

    def __init__(self, nn):
        """
        Initialisation function
        """
    
        rospy.loginfo('Loading model...')
        self.nn = nn
        if self.nn == 'yolact':
            rospy.loginfo("Selected NN: Yolact")
            # Yoloact imports
            # HARDCODED PATH - Temporary fix
            sys.path.append('/home/introlab/catkin_ws_dotmask/src/dotmask/nn/yolact/')
            from yolact import Yolact
            from data import cfg, set_cfg, set_dataset
            import torch
            import torch.backends.cudnn as cudnn 

            set_cfg("yolact_resnet50_config")
            #set_cfg("yolact_resnet50_config")
            cfg.eval_mask_branch = True
            cfg.mask_proto_debug = False
            cfg.rescore_bbox = True
            self.net = Yolact()
            self.net.load_weights("/home/introlab/catkin_ws_dotmask/src/dotmask/weights/yolact_resnet50_54_800000.pth")
            #self.net.load_weights("../weights/yolact_resnet50_54_800000.pth")
            self.net.eval()
            cudnn.fastest = True
            torch.set_default_tensor_type('torch.cuda.FloatTensor')
            self.net = self.net.cuda()
        elif self.nn == 'yolact++':
            rospy.loginfo("Selected NN: Yolact++")
            # Yoloact imports
            # HARDCODED PATH - Temporary fix
            sys.path.append('/home/introlab/catkin_ws_dotmask/src/dotmask/nn/yolact/')
            from yolact import Yolact
            from data import cfg, set_cfg, set_dataset
            import torch
            import torch.backends.cudnn as cudnn 

            set_cfg("yolact_plus_resnet50_config")
            #set_cfg("yolact_resnet50_config")
            cfg.eval_mask_branch = True
            cfg.mask_proto_debug = False
            cfg.rescore_bbox = True
            self.net = Yolact()
            self.net.load_weights("/home/introlab/catkin_ws_dotmask/src/dotmask/weights/yolact_plus_resnet50_54_800000.pth")
            #self.net.load_weights("../weights/yolact_resnet50_54_800000.pth")
            self.net.eval()
            cudnn.fastest = True
            torch.set_default_tensor_type('torch.cuda.FloatTensor')
            self.net = self.net.cuda()

        elif self.nn == 'yolact_edge':
            rospy.loginfo("Selected NN: Yolact_edge")
            #Yoloact_edge imports
            """
            To fix "AttributeError: 'Config' object has no attribute 'mask_proto_debug'"
            https://github.com/dbolya/yolact/issues/256
            For a lack of better solution (or rather inability to find one), I just commented calling mask_proto_debug out in output_utils.py line 63:
                #if cfg.mask_proto_debug:
                #    np.save('scripts/proto.npy', proto_data.cpu().numpy())

            """
            # HARDCODED PATH - Temporary fix
            sys.path.append('/home/introlab/catkin_ws_dotmask/src/dotmask/nn/yolact_edge/yolact_edge')
            sys.path.append('/home/introlab/catkin_ws_dotmask/src/dotmask/nn/yolact_edge/')
            from yolact import Yolact
            from data import cfg, set_cfg, set_dataset
            import torch
            import torch.backends.cudnn as cudnn

            set_cfg("yolact_edge_resnet50_config")
            cfg.eval_mask_branch = True
            cfg.mask_proto_debug = False
            cfg.rescore_bbox = True
            self.net = Yolact()
            self.net.load_weights("/home/introlab/catkin_ws_dotmask/src/dotmask/weights/yolact_edge_resnet50_54_800000.pth")
            self.net.eval()
            cudnn.fastest = True
            torch.set_default_tensor_type('torch.cuda.FloatTensor')
            self.net = self.net.cuda()


        elif self.nn == 'mrcnn':
            rospy.loginfo("Selected NN: Mask-RCNN")
             # Keras
            import keras
            from keras.models import Model
            from keras import backend as K
            K.common.set_image_dim_ordering('tf')

            # Mask-RCNN
            # HARDCODED PATH - Temporary fix
            sys.path.append('/home/introlab/catkin_ws_dotmask/src/dotmask/nn/Mask_RCNN/')
            from mrcnn import config
            from mrcnn import utils 
            from mrcnn import model as modellib
            from inference_config import InferenceConfig

            self.config = InferenceConfig()
            self.model = modellib.MaskRCNN(
                mode="inference", 
                model_dir="/home/introlab/catkin_ws_dotmask/src/dotmask/weights/",#"../nn/Mask_RCNN/mrcnn/", 
                config=self.config)

            # Load weights trained on MS-COCO
            self.model.load_weights("/home/introlab/catkin_ws_dotmask/src/dotmask/weights/mask_rcnn_coco.h5", by_name=True)
        
        else:
            rospy.logerr("No nn defined")

        self.bridge = CvBridge()
        self._max_inactive_frames = 10 # Maximum nb of frames before destruction
        self.next_object_id = 0 # ID for next object
        self.objects_dict = {} # Detected objects dictionary
        self.var_init = 0
        self.cam_pos_qat = np.array([[0.,0.,0.],[0.,0.,0.,1.]])
        self.cam_pos = np.array([[0.,0.,0.],[0.,0.,0.]])

        self.frame = []
        self.depth_frame = []
        self.msg_header = std_msgs.msg.Header()
        self.depth_msg_header = std_msgs.msg.Header()
        self.camera_info_K = np.array(CameraInfo().K).reshape([3, 3])
        #self.camera_info_D = CameraInfo().D

        # Class names COCO dataset - Selected things are objects/obstacles that could move on a map
        # Not used, only for reference
        """self.class_names = [
            'person', 'bicycle', 'car', 'motorcycle',
            'airplane', 'bus', 'train', 'truck', 'boat',
            'traffic light', 'fire hydrant', 'stop sign', 'parking meter', 'bench', 
            'bird', 'cat', 'dog', 'horse', 'sheep', 
            'cow', 'elephant', 'bear', 'zebra', 'giraffe', 
            'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 
            'frisbee', 'skis', 'snowboard', 'sports ball', 'kite', 
            'baseball bat', 'baseball glove', 'skateboard', 'surfboard', 'tennis racket',
            'bottle', 'wine glass', 'cup', 'fork', 'knife', 
            'spoon', 'bowl', 'banana', 'apple', 'sandwich', 
            'orange', 'broccoli', 'carrot', 'hot dog', 'pizza',
            'donut', 'cake', 'chair', 'couch', 'potted plant', 
            'bed', 'dining table', 'toilet', 'tv', 'laptop',
            'mouse', 'remote', 'keyboard', 'cell phone', 'microwave', 
            'oven', 'toaster', 'sink', 'refrigerator', 'book',
            'clock', 'vase', 'scissors', 'teddy bear', 'hair drier', 
            'toothbrush']"""
        
        #Parameters - From launch file param or default

        self.selected_classes = [0] #, 56, 67]
        self.dilatation = rospy.get_param('~dilatation', 10)
        self.score_threshold = rospy.get_param('~score_threshold', 0.8) #Confidence score treshold for limiting/increasing detections
        self.max_number_observation = rospy.get_param('~max_number_observation', 5) #Maximum number (+1) of different objects detected for a specific type (person_x where x is the is the "number_observation)
        self.human_threshold = rospy.get_param('~human_threshold', 0.01) #Minimum velocity to consider a person as "in movement"
        self.object_threshold = rospy.get_param('~object_threshold', 0.3) #Minimum velocity to consider an object as "in movement"
        #IoU : Intersection over Union or (Area of overlap)/(Area of union)
        self.iou_threshold = rospy.get_param('~iou_threshold', 0.9) #Maximum segmentation overlap between frames to consider the object as "in movement"
        self.masked_id = []
        #if input_device == 'xtion':
        #    self.human_threshold = 0.1
        #    self.iou_threshold = 0.3

        self.depth_image_pub = rospy.Publisher("depth_masked_image", Image,queue_size=1)
        self.dynamic_depth_image_pub = rospy.Publisher("depth_dynamic_masked_image", Image,queue_size=1)
        self.colored_detection = rospy.Publisher("colored_detection", Image,queue_size=1)

        
        
    def get_active(self, val):
        for key in self.objects_dict:
            if self.objects_dict[key]["maskID"] == val:
                return self.objects_dict[key]["activeObject"]
        return "Key not exist"

    def read_objects_pose(self):

        for i in self.objects_dict:
            if self.objects_dict[i]["classID"]==0:
                object_type = "Person"
            # elif self.objects_dict[i]["classID"]==39:
            #     object_type = "Bottle"
            # elif self.objects_dict[i]["classID"]==56:
            #     object_type = "Chair"
            else:
                object_type = "Nan"
            try:
                (self.objects_dict[i]["worldPose"],rot) = listener.lookupTransform('/map',object_type+'_'+str(i), rospy.Time(0))
            except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
                continue
                        
    def handle_objects_pose(self):
        for i in self.objects_dict:
            if self.objects_dict[i]["classID"]==0 : #or self.objects_dict[i]["classID"]==39 or self.objects_dict[i]["classID"]==56:
                if self.objects_dict[i]["classID"]==0:
                    object_type = "Person"
                # elif self.objects_dict[i]["classID"]==39:
                #     object_type = "Bottle"
                # elif self.objects_dict[i]["classID"]==56:
                #     object_type = "Chair"
                else:
                    object_type = "Nan"
                
                br = tf.TransformBroadcaster()
                e_pose = self.objects_dict[i]["estimatedPose"]
                br.sendTransform((e_pose[0], e_pose[1], e_pose[2]), 
                                tf.transformations.quaternion_from_euler(0,0,0),
                                rospy.Time.now(),
                                object_type+'_'+str(i),
                                '/map')

    def iou_centered_centroid(self, rois_old, rois_new, mask_old, mask_new):
        # intersection_over_union applied on centered centroid 
        img_v = mask_old.shape[0]
        img_h = mask_old.shape[1]

        pad_x_old = int((img_v-(rois_old[3]-rois_old[1]))/2)
        pad_y_old = int((img_h-(rois_old[2]-rois_old[0]))/2)
        pad_x_new = int((img_v-(rois_new[3]-rois_new[1]))/2)
        pad_y_new = int((img_h-(rois_new[2]-rois_new[0]))/2)

        cropped_mask_old = mask_old[rois_old[1]:rois_old[3], rois_old[0]:rois_old[2]]
        cropped_mask_new = mask_new[rois_new[1]:rois_new[3], rois_new[0]:rois_new[2]]

        centered_mask_old = add_padding(cropped_mask_old, pad_y_old, pad_x_old, pad_y_old, pad_x_old)
        centered_mask_new = add_padding(cropped_mask_new, pad_y_new, pad_x_new, pad_y_new, pad_x_new)

        centered_mask_old_croped = centered_mask_old[1:478, 1:638]
        centered_mask_new_croped = centered_mask_new[1:478, 1:638]

        intersection = np.logical_and(centered_mask_old_croped, centered_mask_new_croped)
        union = np.logical_or(centered_mask_old_croped, centered_mask_new_croped)
        iou = np.sum(intersection) / np.sum(union)
        return iou

    def apply_depth_image_masking(self, image_in, masks):
        """
        Apply the given mask to the image.
        """
        image_masked = copy.deepcopy(image_in)
        image_dynamic_masked = copy.deepcopy(image_in)

        for i in range(masks.shape[0]):
            mask = masks[i, :, :]
            mask = ndimage.binary_dilation(mask, iterations=self.dilatation)
            image_masked[:, :] = np.where(mask == 1, 0, image_masked[:, :])
            if self.get_active(i):
                image_dynamic_masked[:, :] = np.where(mask == 1, 0, image_masked[:, :])
        return image_dynamic_masked, image_masked

    def get_masking_depth(self, image, mask):
        """
        Apply the given mask to the image.
        """
        x = np.zeros([image.shape[0], image.shape[1]])
        y = np.zeros(mask.shape[0])
        for i in range(mask.shape[0]):
            x[:, :] = np.where(mask[i,:,:] != 1,
                                0,
                                image[:, :])

            x[:, :] = np.where( np.isnan(x[:,:]),
                                0,
                                x[:, :])

            if sum(sum((x[:, :]!=0))) == 0:
                y[i] = 0
            else:
                y[i] = (x[:, :].sum()/sum(sum((x[:, :]!=0))))
        return y

    def add_object(self, centroid, dimensions, mask_id, class_id, mask_old, rois_old):
        dt = 0.25

        try:
            (transc, rotc) = listener.lookupTransform('map', self.tf_camera, rospy.Time(0))
        except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
            transc = np.array([0.,0.,0.])
            rotc = np.array([0.,0.,0.,1.])

        euler = tf.transformations.euler_from_quaternion(rotc)
        rot = tf.transformations.euler_matrix(euler[0],euler[1],euler[2])

        h_mat = rot
        h_mat[0:3,3:] = np.array([transc]).T
        b = h_mat.dot(np.array([[centroid[0],centroid[1],centroid[2],1]]).T)[0:3,:]
        
        y = np.array([b[0,0], b[1,0], b[2,0]])

        x = [y[0], y[1], y[2], 0, 0, 0]

        P = np.eye(len(x))

        F = np.array([[ 1,  0,  0, dt,  0,  0],
                      [ 0,  1,  0,  0, dt,  0],
                      [ 0,  0,  1,  0,  0, dt],
                      [ 0,  0,  0,  1,  0,  0],
                      [ 0,  0,  0,  0,  1,  0],
                      [ 0,  0,  0,  0,  0,  1]])

        H = np.array([[ 0.001,  0,  0,  0,  0,  0],
                      [ 0,  0.001,  0,  0,  0,  0],
                      [ 0,  0,  0.001,  0,  0,  0]])

        if class_id == 1:
            ax = 0.68
            ay = 0.68
            az = 0.68
        else:
            ax = 1
            ay = 1
            az = 1

        Q = np.array([[((dt**4)/4)*(ax**2),  0.0,  0.0,  ((dt**4)/4)*(ax**3),  0.0,  0.0],
                      [0.0,  ((dt**4)/4)*(ay**2),  0.0,  0.0, ((dt**4)/4)*(ay**3),   0.0],
                      [0.0,  0.0,  ((dt**4)/4)*(az**2),  0.0,   0.0, ((dt**4)/4)*(az**3)],
                      [((dt**4)/4)*(ax**3),  0.0,  0.0,  (dt**2)*(ax**2),  0.0,  0.0],
                      [0.0,  ((dt**4)/4)*(ay**3),  0.0,  0.0,  (dt**2)*(ax**2),  0.0],
                      [0.0,  0.0,  ((dt**4)/4)*(az**3),  0.0,  0.0, (dt**2)*(ax**2)]])             

        R = np.array([[ 0.8,  0,  0],
                      [ 0,  0.8,  0],
                      [ 0,  0,  1.2]])
        
        self.objects_dict.update({self.next_object_id : {
            "kalmanFilter" : extendedKalmanFilter(x, P, F, H, Q, R),
            "centroid" : centroid,
            "dimension" : dimensions,
            "classID" : class_id,
            "roisOld" : rois_old,
            "maskID" : mask_id,
            "maskOld" : mask_old,
            "worldPose" : [0,0,0],
            "estimatedVelocity" : [0,0,0],
            "estimatedPose" : [0,0,0],
            "inactiveNbFrame" : 0,
            "activeObject" : 0}})
        
        self.next_object_id = self.next_object_id+1
        
    def delete_object(self, object_id):
        del self.objects_dict[object_id]

    def mask_to_centroid(self, rois, mask_depth):
        current_centroids = {}
        current_dimensions = {}
        for i in range(len(rois)):    
            # 3D centroids from depth frame
            
            # Using camera info from camera info topic
            # K matrix = [[fx,  0,  cx],
            #             [0,   fy, cy],
            #             [0,   0,  1]]
            if not self.camera_info_K.any():
                rospy.logerr("Camera info K matrix empty. Check that the camera info topic is correctly set and publishes a valid K.")
            else:
                fx = self.camera_info_K[0,0]
                fy = self.camera_info_K[1,1]
                cx = self.camera_info_K[0,2]
                cy = self.camera_info_K[1,2]
            
            # Translation from depth pixel to local point
            if mask_depth[i] == -1:
                z = 0
            else :
                z = mask_depth[i]
            
            y = (((rois[i,3]+rois[i,1])/2) - cy) * z / fy
            x = (((rois[i,2]+rois[i,0])/2) - cx) * z / fx

            # Translation from point to world coord
            current_centroids.update({i:[x, y, z]})
            current_dimensions.update({i:[rois[i,3]-rois[i,1], rois[i,2]-rois[i,0]]})
        return current_centroids, current_dimensions
        
    def live_analysis(self):
        """
        Function for live stream video masking
        """
        while not rospy.is_shutdown():
            start_time = time.time()
            self.masked_id = []
            current_frame = self.frame
            current_depth_frame = self.depth_frame

            if len(current_frame)==0  or  len(current_depth_frame)==0 :
                rospy.loginfo_once("DOTmask ready, waiting for frame")
                time.sleep(0.1)
            else:
                nn_start_time = time.time()
                if self.nn == 'yolact' or self.nn == 'yolact++' or self.nn == 'yolact_edge':
                    frame = torch.from_numpy(current_frame).cuda().float()
                    batch = FastBaseTransform()(frame.unsqueeze(0))
                    if self.nn == 'yolact_edge':
                        extras = {"backbone": "full", "interrupt":False, "keep_statistics":False, "moving_statistics":None}
                        preds = self.net(batch.cuda(), extras=extras)
                        preds = preds["pred_outs"]
                    else:
                        preds = self.net(batch.cuda())


                    nn_pred_time = time.time()
                    h, w, _ = frame.shape
                    b = {}
                    r = {}
                    b['class_ids'], b['scores'], b['rois'], b['masks'] = postprocess(preds, w, h, score_threshold=self.score_threshold)

                    r['class_ids'] = copy.deepcopy(b['class_ids'].cpu().data.numpy())
                    r['scores'] = copy.deepcopy(b['scores'].cpu().data.numpy())
                    r['rois'] = copy.deepcopy(b['rois'].cpu().data.numpy())
                    r['masks'] = copy.deepcopy(b['masks'].cpu().data.numpy())    
                elif self.nn == 'mrcnn':
                    results = self.model.detect([current_frame],verbose=1)
                    r = results[0]
                    r['masks'] = np.swapaxes(r['masks'],0,2)
                    r['masks'] = np.swapaxes(r['masks'],1,2)

                    for i in range(r['rois'].shape[0]):
                        buff = r['rois'][i]
                        r['rois'][i] = [buff[1],buff[0],buff[3],buff[2]]
                    r['class_ids'] = r['class_ids'] - 1
                #''' Deprecated, did not enhance speed
                j=0
                for i in range(len(r['class_ids'])):
                    if not np.in1d(r['class_ids'][j], self.selected_classes):
                        r['class_ids'] = np.delete(r['class_ids'], j)
                        r['scores']= np.delete(r['scores'], j)
                        r['rois']= np.delete(r['rois'], j,axis=0)
                        r['masks']= np.delete(r['masks'], j, axis=0)
                    else:
                        j=j+1

                self.number_observation = min(self.max_number_observation, r['class_ids'].shape[0])
                for j in range(self.number_observation):
                    if r['scores'][j] < self.score_threshold:
                        self.number_observation = j
                        break
                r['class_ids'] = r['class_ids'][:self.number_observation]
                r['scores'] = r['scores'][:self.number_observation]
                r['rois'] = r['rois'][:self.number_observation]
                r['masks'] = r['masks'][:self.number_observation]

                nn_time = time.time()
                mask_depth = self.get_masking_depth(current_depth_frame, r['masks'])
                
                # Read object tf pose
                self.read_objects_pose()
                
                # Read camera tf pose
                try:
                    (transc, rotc) = listener.lookupTransform(self.tf_camera,'/map', rospy.Time(0))
                except (tf.LookupException, tf.ConnectivityException, tf.ExtrapolationException):
                    transc = np.array([0.,0.,0.])
                    rotc = np.array([0.,0.,0.,1.])

                euler = tf.transformations.euler_from_quaternion(rotc)
                rot = tf.transformations.euler_matrix(euler[0],euler[1],euler[2])
        
                h_mat = rot
                h_mat[0:3,3:] = np.array([transc]).T

                objects_to_delete = []

                # Main filter update and prediction step
                if len(r['rois']) == 0:
                    for i in self.objects_dict:
                        self.objects_dict[i]["inactiveNbFrame"] = self.objects_dict[i]["inactiveNbFrame"] + 1
                        if self.objects_dict[i]["inactiveNbFrame"] > self._max_inactive_frames:                            
                            objects_to_delete.append(i)
                    
                    for i in objects_to_delete:
                        self.delete_object(i)
                        
                else : 
                    current_centroids, current_dimensions = self.mask_to_centroid(r['rois'], mask_depth)

                    if not self.objects_dict:
                        if not len(current_centroids)==0:
                            for i in range(len(current_centroids)):
                                self.add_object(current_centroids[i], current_dimensions[i], i, r['class_ids'][i], r['masks'][i], r['rois'][i])

                            for i in self.objects_dict:
                                self.objects_dict[i]["kalmanFilter"].prediction()
                                self.objects_dict[i]["kalmanFilter"].update(self.objects_dict[i]["centroid"], h_mat)
                                self.objects_dict[i]["estimatedPose"] = self.objects_dict[i]["kalmanFilter"].x[0:3]
                                self.objects_dict[i]["estimatedVelocity"] = self.objects_dict[i]["kalmanFilter"].x[3:6]
                    else:
                        objects_pose = np.zeros((len(self.objects_dict),3))
                        objects_ids = np.zeros((len(self.objects_dict)))
                        index = 0
                        for i in self.objects_dict:
                            objects_pose[index,] = self.objects_dict[i]["centroid"]
                            objects_ids[index] = i
                            index = index + 1

                        centroids_pose = np.zeros((len(current_centroids),3))
                        for i in range(len(current_centroids)):
                            centroids_pose[i,] = current_centroids[i]
                        
                        eucledian_dist_pairwise = np.array(cdist(objects_pose, centroids_pose)).flatten()
                        index_sorted = np.argsort(eucledian_dist_pairwise)

                        used_objects = []
                        used_centroids = []
                        
                        for index in range(len(eucledian_dist_pairwise)):
                            object_id = int(index_sorted[index] / len(centroids_pose))
                            centroid_id = index_sorted[index] % len(centroids_pose)

                            if not np.in1d(object_id, used_objects) and not np.in1d(centroid_id, used_centroids):# and (eucledian_dist_pairwise[index]<0.5):
                                if self.objects_dict[objects_ids[object_id]]["classID"] == r['class_ids'][centroid_id]:
                                    timebefore = time.time()
                                    used_objects.append(object_id)
                                    used_centroids.append(centroid_id)

                                    self.objects_dict[objects_ids[object_id]]["kalmanFilter"].prediction()
                                    self.objects_dict[objects_ids[object_id]]["kalmanFilter"].update(current_centroids[centroid_id], h_mat)
                                    self.objects_dict[objects_ids[object_id]]["estimatedPose"] = self.objects_dict[objects_ids[object_id]]["kalmanFilter"].x[0:3]
                                    self.objects_dict[objects_ids[object_id]]["estimatedVelocity"] = self.objects_dict[objects_ids[object_id]]["kalmanFilter"].x[3:6]

                                    if self.objects_dict[objects_ids[object_id]]["classID"] == 0:
                                        max_threshold = self.human_threshold
                                    else:
                                        max_threshold = self.object_threshold
                                    
                                    if abs(self.objects_dict[objects_ids[object_id]]["estimatedVelocity"][0])>max_threshold or abs(self.objects_dict[objects_ids[object_id]]["estimatedVelocity"][1])>max_threshold or abs(self.objects_dict[objects_ids[object_id]]["estimatedVelocity"][2])>max_threshold:
                                        self.objects_dict[objects_ids[object_id]]["activeObject"] = 1
                                    else:
                                        self.objects_dict[objects_ids[object_id]]["activeObject"] = 0

                                    if self.objects_dict[objects_ids[object_id]]["classID"] == 0 and self.objects_dict[objects_ids[object_id]]["activeObject"] == 0:
                                        
                                        iou = self.iou_centered_centroid(self.objects_dict[objects_ids[object_id]]["roisOld"], r['rois'][centroid_id], self.objects_dict[objects_ids[object_id]]["maskOld"],r['masks'][centroid_id])         
                                        if iou<self.iou_threshold:
                                            self.objects_dict[objects_ids[object_id]]["activeObject"] = 1
                                        else:
                                            x=1
                                    
                                    self.objects_dict[objects_ids[object_id]]["centroid"] = centroids_pose[centroid_id]
                                    self.objects_dict[objects_ids[object_id]]["dimensions"] = current_dimensions[centroid_id]
                                    self.objects_dict[objects_ids[object_id]]["inactiveNbFrame"] = 0
                                    self.objects_dict[objects_ids[object_id]]["maskID"] = centroid_id
                                    self.objects_dict[objects_ids[object_id]]["maskOld"] = r['masks'][centroid_id]
                                    self.objects_dict[objects_ids[object_id]]["roisOld"] = r['rois'][centroid_id]
                        
                        if len(centroids_pose) < len(objects_pose):
                            for index in range(len(eucledian_dist_pairwise)):
                                object_id = int(index_sorted[index] / len(objects_pose))
                                if not np.in1d(object_id, used_objects):
                                    self.objects_dict[objects_ids[object_id]]["inactiveNbFrame"] += 1
                                    self.objects_dict[objects_ids[object_id]]["activeObject"] = 0
                                    if self.objects_dict[objects_ids[object_id]]["inactiveNbFrame"] >= self._max_inactive_frames:
                                        self.delete_object(objects_ids[object_id])
                                        used_objects.append(object_id)
                                    else:
                                        self.objects_dict[objects_ids[object_id]]["kalmanFilter"].prediction()
                                        self.objects_dict[objects_ids[object_id]]["estimatedPose"] = self.objects_dict[objects_ids[object_id]]["kalmanFilter"].x_[0:3]
                                        self.objects_dict[objects_ids[object_id]]["estimatedVelocity"] = self.objects_dict[objects_ids[object_id]]["kalmanFilter"].x_[3:6]

                        elif len(centroids_pose) > len(objects_pose):
                            buff_id = self.next_object_id
                            for index in range(len(eucledian_dist_pairwise)):
                                centroid_id = index_sorted[index] % len(centroids_pose)
                                if not np.in1d(centroid_id, used_centroids):
                                    self.add_object(current_centroids[centroid_id], current_dimensions[centroid_id], centroid_id, r['class_ids'][centroid_id], r['masks'][centroid_id], r['rois'][centroid_id])
                                    self.objects_dict[buff_id]["kalmanFilter"].prediction()
                                    self.objects_dict[buff_id]["kalmanFilter"].update(current_centroids[centroid_id], h_mat)
                                    self.objects_dict[buff_id]["estimatedPose"] = self.objects_dict[buff_id]["kalmanFilter"].x[0:3]
                                    self.objects_dict[buff_id]["estimatedVelocity"] = self.objects_dict[buff_id]["kalmanFilter"].x[3:6]
                                    buff_id = buff_id + 1
                               
                kalman_time = time.time()
                # Write objects filter pose to tf
                self.handle_objects_pose()

                result_dynamic_depth_image, result_depth_image = self.apply_depth_image_masking(current_depth_frame, r['masks'])
                
                DDITS = Image()
                DDITS = self.bridge.cv2_to_imgmsg(result_dynamic_depth_image,'32FC1')
                DDITS.header = self.depth_msg_header
                self.dynamic_depth_image_pub.publish(DDITS)

                DITS = Image()
                DITS = self.bridge.cv2_to_imgmsg(result_depth_image,'32FC1')
                DITS.header = self.depth_msg_header
                self.depth_image_pub.publish(DITS)

                DITS = Image()
                DITS = self.bridge.cv2_to_imgmsg(result_depth_image,'32FC1')
                DITS.header = self.depth_msg_header
                self.colored_detection.publish(DITS)
                
                print_time = time.time()

                #rospy.log(" NN pred time: ", format(nn_pred_time - nn_start_time, '.3f'),", NN post time: ", format(nn_time - nn_pred_time, '.3f'),", NN time: ", format(nn_time - start_time, '.3f'), ", Kalman time: ", format(kalman_time - nn_time, '.3f'),
                #", Print time: ", format(print_time - kalman_time, '.3f'), ", Total time: ", format(time.time() - start_time, '.3f'),
                #", FPS :", format(1/(time.time() - start_time), '.2f'), end="\r")

    def image_callback(self, msg):

        self.msg_header = msg.header
        self.frame = self.bridge.imgmsg_to_cv2(msg, "bgr8")

    def depth_image_callback(self, msg):

        self.depth_msg_header = msg.header
        #32FC1 for asus xtion
        #8UC1 forkicect
        self.depth_frame = self.bridge.imgmsg_to_cv2(msg, "32FC1")
    
    def camera_info_callback(self, camera_info):
        self.camera_info_K = np.array(camera_info.K).reshape([3, 3])
        #self.camera_info_D = np.array(camera_info.D) #Not needed


if __name__ == '__main__':
    parse_args()

    dotmask = DOTMask(args.nn)
    rospy.init_node('ism_node', anonymous=True)

    listener = tf.TransformListener()

    #Use remap in a ROS launch file to launch this node with custom subscribers
    dotmask.tf_camera = rospy.get_param('~camera_optical_frame')
    rospy.Subscriber("rgb/image", Image, dotmask.image_callback)
    rospy.Subscriber("rgb/camera_info", CameraInfo, dotmask.camera_info_callback)
    rospy.Subscriber("depth/image", Image, dotmask.depth_image_callback)

    if args.nn == "yolact" or args.nn == "yolact++" or args.nn == "yolact_edge":
        from utils.augmentations import BaseTransform, FastBaseTransform, Resize
        
        from data import COCODetection, get_label_map, MEANS, COLORS
        from layers.output_utils import postprocess
        
        import torch 
        with torch.no_grad():
            dotmask.live_analysis()
    elif args.nn == "mrcnn":
        dotmask.live_analysis()
    try:
        rospy.spin()
    except rospy.ROSInterruptException:
        rospy.loginfo("Shutting down artificial neural network")
