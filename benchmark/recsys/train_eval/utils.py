import os
import shutil
from torch.utils.data import TensorDataset, DataLoader

import torch
from torch import optim


def cleardir(path):
    if os.path.isdir(path):
        for file in os.listdir(path):
            file_path = os.path.join(path, file)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path): shutil.rmtree(file_path)
            except Exception as e:
                print(e)


def get_iters(data, batch_size=128):
    edge_iter = DataLoader(
        TensorDataset(
            data.edge_index.t()[data.train_edge_mask],
            data.edge_attr[data.train_edge_mask],
        ),
        batch_size=batch_size,
        shuffle=True
    )

    train_rating_edge_iter = DataLoader(
        TensorDataset(
            data.edge_index.t()[data.train_edge_mask * data.rating_edge_mask],
            data.edge_attr[data.train_edge_mask * data.rating_edge_mask],
        ),
        batch_size=batch_size,
        shuffle=True
    )

    test_rating_edge_iter = DataLoader(
        TensorDataset(
            data.edge_index.t()[data.test_edge_mask * data.rating_edge_mask],
            data.edge_attr[data.test_edge_mask * data.rating_edge_mask],
        ),
        batch_size=batch_size,
        shuffle=True
    )

    return edge_iter, train_rating_edge_iter, test_rating_edge_iter


def get_opt(opt_type, model, lr=10e-3, weight_decay=0):
    if opt_type == 'adam':
        opt = optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)
    else:
        raise ValueError('{} not implemented!'.format(opt_type))

    return opt


def get_loss_func(loss_func_type):
    if loss_func_type == 'mse':
        loss_func = torch.nn.MSELoss()
    else:
        raise ValueError('{} not implemented!'.format(loss_func_type))

    return loss_func