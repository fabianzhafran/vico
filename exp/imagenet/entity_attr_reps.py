import os
import h5py
import math
import copy
from tqdm import tqdm
import torch
import torch.nn as nn
import itertools
from torch.utils.data import DataLoader
from torch.autograd import Variable
import torch.optim as optim
from tensorboard_logger import configure, log_value
import numpy as np
from collections import deque

import utils.io as io
from utils.model import Model
from utils.constants import save_constants
import utils.pytorch_layers as pytorch_layers
from exp.genome_attributes.models.resnet_normalized import ResnetNormalizedModel
from .dataset import ImagenetDataset
from .vis.vis_sim_mat import create_sim_heatmap


def compute_entity_attr_reps(model,dataloader,exp_const):
    num_classes = len(dataloader.dataset.wnids)
    rep_dim = model.net.resnet_layers.fc.weight.size(1)

    print('Allocating memory for storing entity-attr reps ...')
    reps = np.zeros([num_classes,rep_dim],dtype=np.float32)
    num_imgs_per_class = np.zeros([num_classes],dtype=np.int32)
    
    img_mean = Variable(torch.cuda.FloatTensor(model.img_mean),volatile=True)
    img_std = Variable(torch.cuda.FloatTensor(model.img_std),volatile=True)
    
    # Set mode
    model.net.eval()

    print('Aggregating image features ...')
    for it,data in enumerate(tqdm(dataloader)):
        # Forward pass
        imgs = Variable(data['img'].cuda().float()/255.,volatile=True)
        imgs = dataloader.dataset.normalize(
            imgs,
            img_mean,
            img_std)
        imgs = imgs.permute(0,3,1,2)
        last_layer_feats_normalized, _ = model.net.forward_features_only(imgs)
        last_layer_feats_normalized = \
            last_layer_feats_normalized.data.cpu().numpy()
        for b in range(last_layer_feats_normalized.shape[0]):
            on_wnids = data['on_wnids'][b]
            for wnid in on_wnids:
                i = dataloader.dataset.wnid_to_idx[wnid]
                num_imgs_per_class[i] = num_imgs_per_class[i] + 1
                reps[i] = reps[i] + last_layer_feats_normalized[b]

    reps = reps / (num_imgs_per_class[:,None]+1e-6)
    reps = reps / (np.linalg.norm(reps,ord=2,axis=1,keepdims=True)+1e-6)

    print('Saving entity-attr reps and related files ...')
    np.save(os.path.join(exp_const.exp_dir,'reps.npy'),reps)
    np.save(
        os.path.join(exp_const.exp_dir,'num_imgs_per_class.npy'),
        num_imgs_per_class)
    io.dump_json_object(
        dataloader.dataset.wnid_to_idx,
        os.path.join(exp_const.exp_dir,'wnid_to_idx.json'))


def main(exp_const,data_const,model_const):
    io.mkdir_if_not_exists(exp_const.exp_dir,recursive=True)
    save_constants(
        {'exp': exp_const,'data': data_const,'model': model_const},
        exp_const.exp_dir)
    
    print('Creating network ...')
    model = Model()
    model.const = model_const
    model.net = ResnetNormalizedModel(model.const.net)
    if model.const.model_num is not None:
        model.net.load_state_dict(torch.load(model.const.net_path))
    model.net.cuda()
    model.img_mean = np.array([0.485, 0.456, 0.406])
    model.img_std = np.array([0.229, 0.224, 0.225])
    model.to_file(os.path.join(exp_const.exp_dir,'model.txt'))

    print('Creating dataloader ...')
    data_const = copy.deepcopy(data_const)
    dataset = ImagenetDataset(data_const)
    collate_fn = dataset.create_collate_fn()
    dataloader = DataLoader(
        dataset,
        batch_size=exp_const.batch_size,
        shuffle=True,
        num_workers=exp_const.num_workers,
        collate_fn=collate_fn)

    print('Mean Image Features Based Entity-Attr Reps ...')
    compute_entity_attr_reps(model,dataloader,exp_const)