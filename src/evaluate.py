import os
from src import utils
from src.sample_tracker import Tracker

import cv2 as cv
import numpy as np

class Video:
    def __init__(self, case_sample_path, is_to_rectify):
        # Load video info
        self.case_sample_path = case_sample_path
        video_info_path = os.path.join(case_sample_path, "info.yaml")
        video_info = utils.load_yaml_data(video_info_path)
        #print(video_info)
        self.stack_type = video_info["video_stack"]
        self.im_height = video_info["resolution"]["height"]
        self.im_width = video_info["resolution"]["width"]
        # Load rectification data
        self.is_to_rectify = is_to_rectify
        if is_to_rectify:
            self.calib_path = os.path.join(case_sample_path, "calibration.yaml")
            utils.is_path_file(self.calib_path)
            self.load_calib_data()
            self.stereo_rectify()
            self.get_rectification_maps()
        # Load video
        name_video = video_info["name_video"]
        self.video_path = os.path.join(case_sample_path, name_video)
        #print(self.video_path)
        self.video_restart()
        # Load ground-truth
        self.gt_files = video_info["name_ground_truth"]
        self.n_keypoints = len(self.gt_files)


    def video_restart(self):
        self.cap = cv.VideoCapture(self.video_path)
        self.frame_counter = -1 # So that the first get_frame() goes to zero


    def load_ground_truth(self, ind_kpt):
        gt_data_path = os.path.join(self.case_sample_path, self.gt_files[ind_kpt])
        self.gt_data = utils.load_yaml_data(gt_data_path)


    def get_bbox_gt(self, frame_counter):
        """
            Return two bboxes in format (u, v, width, height)

                                 (u,)   (u + width,)
                          (0,0)---.--------.---->
                            |
                       (,v) -     x--------.
                            |     |  bbox  |
              (,v + height) -     .________.
                            v

            Note: we assume that the gt coordinates are already set for the
                  rectified images, otherwise we would have to re-map these coordinates.
        """
        bbox_1 = None
        bbox_2 = None
        is_difficult = None
        bbxs = self.gt_data[frame_counter]
        if bbxs is not None:
            bbox_1 = bbxs[0][0]
            bbox_2 = bbxs[0][1]
            is_difficult = bbxs[1]
        return bbox_1, bbox_2, is_difficult


    def load_calib_data(self):
        fs = cv.FileStorage(self.calib_path, cv.FILE_STORAGE_READ)
        self.r = np.array(fs.getNode('R').mat(), dtype=np.float64)
        self.t = np.array(fs.getNode('T').mat()[0], dtype=np.float64)
        self.m1 = np.array(fs.getNode('M1').mat(), dtype=np.float64)
        self.d1 = np.array(fs.getNode('D1').mat()[0], dtype=np.float64)
        self.m2 = np.array(fs.getNode('M2').mat(), dtype=np.float64)
        self.d2 = np.array(fs.getNode('D2').mat()[0], dtype=np.float64)


    def stereo_rectify(self):
        self.R1, self.R2, self.P1, self.P2, self.Q, _roi1, _roi2 = \
            cv.stereoRectify(cameraMatrix1=self.m1,
                             distCoeffs1=self.d1,
                             cameraMatrix2=self.m2,
                             distCoeffs2=self.d2,
                             imageSize=(self.im_width, self.im_height),
                             R=self.r,
                             T=self.t,
                             flags=cv.CALIB_ZERO_DISPARITY,
                             alpha=0.0
                            )


    def get_rectification_maps(self):
        self.map1_x, self.map1_y = \
            cv.initUndistortRectifyMap(cameraMatrix=self.m1,
                                       distCoeffs=self.d1,
                                       R=self.R1,
                                       newCameraMatrix=self.P1,
                                       size=(self.im_width, self.im_height),
                                       m1type=cv.CV_32FC1
                                      )

        self.map2_x, self.map2_y = \
            cv.initUndistortRectifyMap(
                                       cameraMatrix=self.m2,
                                       distCoeffs=self.d2,
                                       R=self.R2,
                                       newCameraMatrix=self.P2,
                                       size=(self.im_width, self.im_height),
                                       m1type=cv.CV_32FC1
                                      )


    def split_frame(self, frame):
        if self.stack_type == "vertical":
            im1 = frame[:self.im_height, :]
            im2 = frame[self.im_height:, :]
        elif self.stack_type == "horizontal":
            im1 = frame[:, :self.im_width]
            im2 = frame[:, self.im_width:]
        else:
            print("Error: unrecognized stack type `{}`!".format(stack_type))
            exit()
        if self.is_to_rectify:
            im1 = cv.remap(im1, self.map1_x, self.map1_y, cv.INTER_LINEAR)
            im2 = cv.remap(im2, self.map2_x, self.map2_y, cv.INTER_LINEAR)
        return im1, im2


    def get_frame(self):
        if self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                self.frame_counter += 1
                return frame, self.frame_counter
        self.cap.release()
        return None, self.frame_counter


    def stop_video(self):
        self.cap.release()


class Statistics:
    def __init__(self):
        self.acc_list = []
        self.rob_list = []


    def append_stats(self, acc, rob):
        self.acc_list.append(acc)
        self.rob_list.append(rob)


    def get_stats_mean(self):
        mean_acc = np.mean(self.acc_list)
        mean_rob = np.mean(self.rob_list)
        return mean_acc, mean_rob


class EAO_Rank:
    def __init__(self):
        self.all_padded_ss_list = []


    def append_ss_list(self, padded_list):
        self.all_padded_ss_list += padded_list


    def update_max_ss_length(self):
        self.max_ss_len = 0
        for ss in self.all_padded_ss_list:
            if ss:
                # If list not empty
                len_ss = len(ss)
                if len_ss > self.max_ss_len:
                    self.max_ss_len = len_ss
        

    def calculate_eao_curve(self):
        self.eao_curve = []
        self.update_max_ss_length()
        for i in range(self.max_ss_len):
            score = 0
            ss_sum = 0.0
            ss_counter = 0
            for ss in self.all_padded_ss_list:
                if len(ss) > i:
                    if ss[i] == "is_difficult":
                        continue
                    ss_sum += ss[i]
                    ss_counter += 1
            if ss_counter == 0:
                # No more sequences
                break
            score = ss_sum / ss_counter
            self.eao_curve.append(score)


    def calculate_eao_score(self):
        self.calculate_eao_curve()
        if not self.eao_curve:
            # If empty list
            return 0.0
        return np.mean(self.eao_curve)
        

class SSeq:
    def __init__(self):
        # Initalized once per video
        self.start_sub_sequence = 0  # frame count for the start of every ss
        self.sub_sequence_current = []  # all successful tracking vectors within a sub sequence
        self.accumulate_ss_iou = []  # accumulates the IoU scores of the running tracker
        self.padded_list = []


    def append_padded_vector(self, padded_vec):
        self.padded_list.append(padded_vec)



class KptResults:
    def __init__(self, n_misses_allowed, iou_threshold):
        self.n_misses_allowed = n_misses_allowed
        self.iou_threshold = iou_threshold
        self.iou_list = []
        self.robustness_frames_counter = 0
        self.n_excessive_frames = 0
        self.n_visible = 0
        self.n_misses_successive = 0


    def reset_n_successive_misses(self):
        self.n_misses_successive = 0


    def calculate_bbox_metrics(self, bbox1_gt, bbox1_p, bbox2_gt, bbox2_p):
        """
        Check if stereo tracking is a success or not
        """
        if bbox1_gt is None or bbox2_gt is None:
            if bbox1_p is not None or bbox2_p is not None:
                # If the tracker made a prediction when the target is not visible
                self.n_excessive_frames += 1
            return False, None
        self.n_visible += 1

        iou = 0
        iou1 = 0
        iou2 = 0
        if bbox1_p is not None and bbox2_p is not None:
            iou1 = self.get_iou(bbox1_gt, bbox1_p)
            iou2 = self.get_iou(bbox2_gt, bbox2_p)
            # Use the mean overlap between the two images
            iou = np.mean([iou1, iou2])
        self.iou_list.append(iou)
        if iou1 > self.iou_threshold and iou2 > self.iou_threshold:
            self.robustness_frames_counter += 1
            self.reset_n_successive_misses()
        # Otherwise it missed
        self.n_misses_successive += 1
        if self.n_misses_successive > self.n_misses_allowed:
            # Keep only the IoUs before tracking failure
            del self.iou_list[-self.n_misses_successive:]
            self.reset_n_successive_misses()
            return True, iou
        return False, iou


    def get_iou(self, bbox_gt, bbox_p):
        x1, y1, x2, y2 = [bbox_gt[0], bbox_gt[1], bbox_gt[0]+bbox_gt[2], bbox_gt[1]+bbox_gt[3]]
        x3, y3, x4, y4 = [bbox_p[0], bbox_p[1], bbox_p[0]+bbox_p[2], bbox_p[1]+bbox_p[3]]
        x_inter1 = max(x1, x3)
        y_inter1 = max(y1, y3)
        x_inter2 = min(x2, x4)
        y_inter2 = min(y2, y4)
        widthinter = np.maximum(0,x_inter2 - x_inter1)
        heightinter = np.maximum(0,y_inter2 - y_inter1)
        areainter = widthinter * heightinter
        widthboxl = abs(x2 - x1)
        heightboxl = abs(y2 - y1)
        widthbox2 = abs(x4 - x3)
        heightbox2 = abs(y4 - y3)
        areaboxl = widthboxl * heightboxl
        areabox2 = widthbox2 * heightbox2
        areaunion = areaboxl + areabox2 - areainter
        iou = areainter / float(areaunion)
        assert(iou >= 0.0 and iou <= 1.0)
        return iou


    def get_accuracy_score(self):
        acc = 1.0
        if self.n_visible > 0:
            acc = np.sum(self.iou_list) / self.n_visible
        assert(acc >= 0.0 and acc <= 1.0)
        return acc


    def get_robustness_score(self):
        rob = 1.0
        denominator = self.n_visible + self.n_excessive_frames
        if denominator > 0:
            rob = self.robustness_frames_counter / denominator
        assert(rob >= 0.0 and rob <= 1.0)
        return rob

    def get_full_metric(self):
        """
        Only happens after all frames are processed, end of video for-loop!
        """
        acc = self.get_accuracy_score()
        rob = self.get_robustness_score()
        return acc, rob



def get_bbox_corners(bbox):
    top_left = (bbox[0], bbox[1])
    bot_right = (bbox[0] + bbox[2], bbox[1] + bbox[3])
    return top_left, bot_right


def draw_bb_in_frame(im1, im2, bbox1_gt, bbox1_p, bbox2_gt, bbox2_p, is_difficult, thck):
    color_gt = (0, 255, 0)  # Green (If the ground-truth is used to assess)
    color_p = (255, 0, 0)  # Blue (Prediction always shown in Blue)
    if is_difficult:
        color_gt = (0, 215, 255) # Orange (If the ground-truth is NOT used to assess)
    # Ground-truth
    if bbox1_gt is not None:
        top_left, bot_right = get_bbox_corners(bbox1_gt)
        im1 = cv.rectangle(im1, top_left, bot_right, color_gt, thck)
    if bbox2_gt is not None:
        top_left, bot_right = get_bbox_corners(bbox2_gt)
        im2 = cv.rectangle(im2, top_left, bot_right, color_gt, thck)
    # Predicted
    if bbox1_p is not None:
        top_left, bot_right = get_bbox_corners(bbox1_p)
        im1 = cv.rectangle(im1, top_left, bot_right, color_p, thck)
    if bbox2_p is not None:
        top_left, bot_right = get_bbox_corners(bbox2_p)
        im2 = cv.rectangle(im2, top_left, bot_right, color_p, thck)
    im_hstack = np.hstack((im1, im2))
    return im_hstack


def assess_bbox(ss, frame_counter, kr, bbox1_gt, bbox1_p, bbox2_gt, bbox2_p, is_difficult):
    if is_difficult:
        # If `is_difficult` then the metrics are not be affected
        ss.accumulate_ss_iou.append("is_difficult")
        return False

    if bbox1_gt is None or bbox2_gt is None:  # if GT is none, its the end of a ss
        if len(ss.sub_sequence_current) > 0:
            ss.sub_sequence_current.append(ss.accumulate_ss_iou)  # appends the final IoU vector
            ss.accumulate_ss_iou = []
            ss.end_sub_sequence = frame_counter  # frame end of ss
            bias = 0  # start at end frame of previous vector
            for ss_tmp in ss.sub_sequence_current:
                pad_req = ss.end_sub_sequence-ss.start_sub_sequence-len(ss_tmp)-bias  # length of padding req
                ss.append_padded_vector(ss_tmp + [0.] * pad_req)  # padding and appending to list
                bias += len(ss_tmp)
            ss.sub_sequence_current = []
        ss.start_sub_sequence = frame_counter + 1

    reset_flag, iou = kr.calculate_bbox_metrics(bbox1_gt, bbox1_p, bbox2_gt, bbox2_p)
    if reset_flag:
        ss.sub_sequence_current.append(ss.accumulate_ss_iou)
        ss.accumulate_ss_iou = []
    else:
        if iou is not None:
            ss.accumulate_ss_iou.append(iou)
    return reset_flag


def assess_keypoint(v, kr, ss):
    # Create window for results animation
    window_name = "Assessment animation"  # TODO: hardcoded
    thick = 2  # TODO: hardcoded
    bbox1_p, bbox2_p = None, None # For the visual animation
    cv.namedWindow(window_name, cv.WINDOW_KEEPRATIO)

    # Use video and load a specific key point
    t = None
    while v.cap.isOpened():
        # Get data of new frame
        frame, frame_counter = v.get_frame()
        if frame is None:
            break
        im1, im2 = v.split_frame(frame)
        bbox1_gt, bbox2_gt, is_difficult = v.get_bbox_gt(frame_counter)

        if t is None:
            # Initialise or re-initialize the tracker
            if bbox1_gt is not None and bbox2_gt is not None:
                # We can only initialize if we have ground-truth bboxes
                if not is_difficult:
                    # Only if bbox is not difficult to track
                    t = Tracker(im1, im2, bbox1_gt, bbox2_gt)
        else:
            # Update the tracker
            bbox1_p, bbox2_p = t.tracker_update(im1, im2)
            # Compute metrics for video and keep track of sub-sequences
            reset_flag = assess_bbox(ss,
                                     frame_counter,
                                     kr,
                                     bbox1_gt, bbox1_p,
                                     bbox2_gt, bbox2_p,
                                     is_difficult)
            if reset_flag:
                # If the tracker failed then we need to set it to None so that we re-initialize
                t = None
                # In visual animation, we hide the last predicted bboxs when the tracker fails
                bbox1_p, bbox2_p = None, None

        # Show animation of the tracker
        frame_aug = draw_bb_in_frame(im1, im2,
                                     bbox1_gt, bbox1_p,
                                     bbox2_gt, bbox2_p,
                                     is_difficult,
                                     thick)
        cv.imshow(window_name, frame_aug)
        cv.waitKey(1)

    # Do one last to finish the sub-sequences without changing the results
    assess_bbox(ss, frame_counter, kr, None, None, None, None, False)


def calculate_results_for_video(rank, case_sample_path, is_to_rectify, config_results):
    # Load video
    v = Video(case_sample_path, is_to_rectify)

    # for when there are multiple keypoints
    stats = Statistics()

    # Iterate through all the keypoints
    for ind_kpt in range(v.n_keypoints):
        # Load ground-truth for the specific keypoint being tested
        v.load_ground_truth(ind_kpt)
        kr = KptResults(config_results["n_misses_allowed"],
                        config_results["iou_threshold"])
        ss = SSeq()
        assess_keypoint(v, kr, ss)
        rank.append_ss_list(ss.padded_list)
        acc, rob = kr.get_full_metric()
        stats.append_stats(acc, rob)
        # Re-start video for assessing the next keypoint
        v.video_restart()

    # Check that we have statistics for each of the keypoints
    assert(len(stats.acc_list) == v.n_keypoints)

    # Stop video after assessing all the keypoints of that specific video
    v.stop_video()

    return stats.get_stats_mean()


def print_results(str_start, acc, rob):
    print("{} Acc:{:.3f} Rob:{:.3f}".format(str_start, acc, rob))


def calculate_case_statitics(case_id, stats_case, stats_case_all):
    if case_id != -1:
        mean_acc, mean_rob = stats_case.get_stats_mean()
        print_results( "\tCase:{}".format(case_id), mean_acc, mean_rob)
        # Append them to final statistics
        stats_case_all.append_stats(mean_acc, mean_rob)

    
def calculate_results(config, valid_or_test):
    config_results = config["results"]
    is_to_rectify = config["is_to_rectify"]
    config_data = config[valid_or_test]

    rank = EAO_Rank()
    case_id_prev = -1
    stats_case = Statistics() # For a specific case
    stats_case_all = Statistics() # For ALL cases

    if config_data["is_to_evaluate"]:
        print('{} dataset'.format(valid_or_test).upper())
        case_samples = utils.get_case_samples(config_data)
        # Go through each video
        for cs in case_samples:
            if cs.case_id != case_id_prev:
                calculate_case_statitics(case_id_prev, stats_case, stats_case_all)
                stats_case = Statistics() # For a specific case
                case_id_prev = cs.case_id
            acc, rob = calculate_results_for_video(rank, cs.case_sample_path, is_to_rectify, config_results)
            print_results("\t\t{}".format(cs.case_sample_path), acc, rob)
            stats_case.append_stats(acc, rob)
        # Calculate statistics of the last case, at the end of for-loop
        calculate_case_statitics(cs.case_id, stats_case, stats_case_all)

        mean_acc, mean_rob = stats_case_all.get_stats_mean()
        print('{} final score:'.format(valid_or_test).upper())
        eao = rank.calculate_eao_score()
        print_results("\tEAO:{:.3f}".format(eao), mean_acc, mean_rob)


def evaluate_method(config):
    calculate_results(config, "validation")
    calculate_results(config, "test")
