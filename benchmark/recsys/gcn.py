__model__ = 'GCN'

import argparse
import os.path as osp
import torch

from torch_geometric.datasets import MovieLens

from train_eval import single_run_with_kg
from models import GCNNet

# Parse arguments
parser = argparse.ArgumentParser()
parser.add_argument("--n_core", type=int, default=20, help="")

parser.add_argument("--hidden_size", type=int, default=128, help="")

parser.add_argument("--device", type=str, default='cuda', help="")
parser.add_argument("--gpu_idx", type=str, default='7', help="")
parser.add_argument("--train_ratio", type=float, default=0.8, help="")
parser.add_argument("--debug", default=0.1, help="")
parser.add_argument("--epochs", type=int, default=1, help="")
parser.add_argument("--batch_size", type=int, default=1024, help="")
parser.add_argument("--lr", type=float, default=1e-3, help="")
parser.add_argument("--weight_decay", type=float, default=0, help="")
parser.add_argument("--early_stopping", type=int, default=40, help="")


parser.add_argument("--emb_dim", type=int, default=300, help="")
parser.add_argument("--repr_dim", type=int, default=32, help="")

args = parser.parse_args()


# Setup data and weights file path
data_path = osp.join(osp.dirname(osp.realpath(__file__)), '..', 'data', '1m')
weights_path = osp.join(osp.dirname(osp.realpath(__file__)), '..', 'weights', __model__,'1m')

# Setup the torch device
device = torch.device(args.device if args.device == 'cpu' else args.device + ':{}'.format(args.gpu_idx))
torch.random.manual_seed(2019)

# Display the arguments used in the experiments
dataset_args = {
    'root': data_path, 'name': '1m', 'n_core': args.n_core, 'sec_order': False,
    'train_ratio': args.train_ratio, 'debug': args.debug
}
task_args = {'emb_dim': args.emb_dim, 'repr_dim': args.repr_dim}
train_args = {
    'debug': args.debug,
    'epochs': args.epochs, 'batch_size': args.batch_size, 'weight_decay': args.weight_decay,
    'lr': args.lr, 'device': device,
    'weights_path': weights_path, 'hidden_size': args.hidden_size}
print('dataset params: {}'.format(dataset_args))
print('task params: {}'.format(task_args))
print('train params: {}'.format(train_args))

data = MovieLens(**dataset_args).data


def main():
    model = GCNNet(args.hidden_size, args.emb_dim, args.repr_dim, data.num_nodes[0], data.num_relations[0])
    cf_loss_func = torch.nn.MSELoss()
    single_run_with_kg(model, data, cf_loss_func, train_args)


if __name__ == '__main__':
    main()
