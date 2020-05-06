import argparse
import torch
import os
from torch_geometric.datasets import MovieLens
from torch.optim import Adam
import time
import numpy as np
import tqdm
import random as rd
import pandas as pd

from utils import get_folder_path, save_model, load_model, save_global_logger, load_global_logger
from models import GCN
from utils import metrics


MODEL = 'GCN'

parser = argparse.ArgumentParser()
# Dataset params
parser.add_argument("--dataset", type=str, default='movielens', help="")
parser.add_argument("--dataset_name", type=str, default='1m', help="")
parser.add_argument("--num_core", type=int, default=10, help="")
parser.add_argument("--num_feat_core", type=int, default=10, help="")
parser.add_argument("--train_ratio", type=float, default=0.8, help="")
# Model params
parser.add_argument("--dropout", type=float, default=0.5, help="")
parser.add_argument("--repr_dim", type=int, default=16, help="")
parser.add_argument("--hidden_size", type=int, default=64, help="")
# Train params
parser.add_argument("--device", type=str, default='cuda', help="")
parser.add_argument("--gpu_idx", type=str, default='0', help="")
parser.add_argument("--runs", type=int, default=100, help="")
parser.add_argument("--epochs", type=int, default=1000, help="")
parser.add_argument("--opt", type=str, default='adam', help="")
parser.add_argument("--loss", type=str, default='mse', help="")
parser.add_argument("--batch_size", type=int, default=4, help="")
parser.add_argument("--lr", type=float, default=1e-4, help="")
parser.add_argument("--weight_decay", type=float, default=1e-3, help="")
parser.add_argument("--early_stopping", type=int, default=40, help="")
parser.add_argument("--save_epochs", type=list, default=[10, 20, 30], help="")
parser.add_argument("--save_every_epoch", type=int, default=30, help="")


# Recommender params
parser.add_argument("--num_recs", type=int, default=10, help="")
args = parser.parse_args()


# Setup data and weights file path
data_folder, weights_folder, logger_folder = \
    get_folder_path(model=MODEL, dataset=args.dataset + args.dataset_name)

# Setup device
if not torch.cuda.is_available() or args.device == 'cpu':
    device = 'cpu'
else:
    device = 'cuda:{}'.format(args.gpu_idx)

# Setup args
dataset_args = {
    'root': data_folder, 'dataset': args.dataset, 'name': args.dataset_name,
    'num_core': args.num_core, 'num_feat_core': args.num_feat_core,
    'train_ratio': args.train_ratio
}
model_args = {
    'hidden_size': args.hidden_size,
    'repr_dim': args.repr_dim, 'dropout': args.dropout
}
train_args = {
    'opt': args.opt, 'loss': args.loss,
    'runs': args.runs, 'epochs': args.epochs, 'batch_size': args.batch_size,
    'weight_decay': args.weight_decay, 'lr': args.lr, 'device': device,
    'weights_folder': os.path.join(weights_folder, str(model_args)),
    'logger_folder': os.path.join(logger_folder, str(model_args)),
    'save_epochs': args.save_epochs, 'save_every_epoch': args.save_every_epoch
}
rec_args = {
    'num_recs': args.num_recs
}
print('dataset params: {}'.format(dataset_args))
print('task params: {}'.format(model_args))
print('train params: {}'.format(train_args))
print('rec params: {}'.format(rec_args))


if __name__ == '__main__':
    global_logger_path = os.path.join(train_args['logger_folder'], 'global_logger.pkl')
    HR_per_run, NDCG_per_run, ROC_per_run, loss_per_run, start_run = load_global_logger(global_logger_path)
    for run in range(start_run, train_args['runs'] + 1):
        # Fix the random seed
        seed = 2019 + run
        rd.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        torch.cuda.manual_seed(seed)

        # Create the dataset
        dataset_args['seed'] = seed
        dataset = MovieLens(**dataset_args)
        data = dataset.data.to(train_args['device'])
        train_pos_unid_inid_map, test_pos_unid_inid_map, neg_unid_inid_map = \
            data.train_pos_unid_inid_map[0], data.test_pos_unid_inid_map[0], data.neg_unid_inid_map[0]
        edge_index_np = np.hstack(list(data.edge_index_nps[0].values()))
        edge_index_np = np.hstack([edge_index_np, np.flip(edge_index_np, 0)])
        edge_index = torch.from_numpy(edge_index_np).long().to(train_args['device'])
        x = data.x

        # Create model and optimizer
        model_args['emb_dim'] = data.num_node_types
        model_args['num_nodes'] = data.x.shape[0]
        model = GCN(**model_args).to(train_args['device'])

        optimizer = Adam(
            params=model.parameters(),
            lr=train_args['lr'],
            weight_decay=train_args['weight_decay']
        )

        # Load models
        weightpath = os.path.join(train_args['weights_folder'], 'run' + str(run), 'latest.pkl')
        model, optimizer, epoch, rec_metrics = load_model(weightpath, model, optimizer, train_args['device'])
        start_epoch = epoch + 1
        HR_history, NDCG_history, AUC_history, loss_history = rec_metrics if rec_metrics is not None else ([], [], [])

        if torch.cuda.is_available():
            torch.cuda.synchronize()

        # Evaluate the random initialized model
        if start_epoch == 1:
            HR_before, NDCG_before, AUC_before, loss_before = metrics(
                start_epoch,
                model(x, edge_index),
                test_pos_unid_inid_map, neg_unid_inid_map,
                rec_args)
            print('Initial performance: HR: {:.4f}, NDCG: {:.4f}, ROC: {:.4f} Loss: {:.4f}'.format(HR_before, NDCG_before, AUC_before, loss_before))

        # Start training model
        t_start = time.perf_counter()
        for epoch in range(start_epoch, train_args['epochs'] + 1):
            model.train()
            epoch_losses = []
            u_nids = list(train_pos_unid_inid_map.keys())
            rd.shuffle(u_nids)
            train_bar = tqdm.tqdm(u_nids, total=len(u_nids))
            for u_idx, u_nid in enumerate(train_bar):
                pos_i_nids = train_pos_unid_inid_map[u_nid]
                # TODO: negative sampling
                neg_i_nids = neg_unid_inid_map[u_nid] + test_pos_unid_inid_map[u_nid]
                if len(pos_i_nids) == 0 or len(neg_i_nids) == 0:
                    continue

                pos_i_nid_df = pd.DataFrame({'u_nid': [u_nid for _ in range(len(pos_i_nids))], 'pos_i_nid': pos_i_nids})
                neg_i_nid_df = pd.DataFrame({'u_nid': [u_nid for _ in range(len(neg_i_nids))], 'neg_i_nid': neg_i_nids})
                pos_neg_pair_np = pd.merge(pos_i_nid_df, neg_i_nid_df, how='inner', on='u_nid').to_numpy()

                propagated_node_emb = model(x, edge_index)

                u_node_emb = propagated_node_emb[pos_neg_pair_np[:, 0]]
                pos_i_node_emb = propagated_node_emb[pos_neg_pair_np[:, 1]]
                neg_i_node_emb = propagated_node_emb[pos_neg_pair_np[:, 2]]
                pred_pos = (u_node_emb * pos_i_node_emb).sum(dim=1)
                pred_neg = (u_node_emb * neg_i_node_emb).sum(dim=1)
                loss = - (pred_pos - pred_neg).sigmoid().log().mean()
                loss.backward()
                optimizer.step()
                optimizer.zero_grad()

                epoch_losses.append(loss.cpu().item())
                train_bar.set_description('Epoch {} and user {} loss {:.4f}'.format(epoch, u_idx,  np.mean(epoch_losses)))

            if epoch in train_args['save_epochs']:
                weightpath = os.path.join(train_args['weights_folder'], '{}.pkl'.format(epoch))
                save_model(weightpath, model, optimizer, epoch, rec_metrics=(HR_history, NDCG_history, loss_history))
            if epoch > train_args['save_every_epoch']:
                weightpath = os.path.join(train_args['weights_folder'], 'latest.pkl')
                save_model(weightpath, model, optimizer, epoch, rec_metrics=(HR_history, NDCG_history, loss_history))

            model.eval()
            HR, NDCG, ROC, loss = metrics(
                epoch,
                model(x, edge_index),
                test_pos_unid_inid_map, neg_unid_inid_map,
                rec_args)

            print('Epoch: {}, HR: {:.4f}, NDCG: {:.4f}, ROC: {:.4f} Loss: {:.4f}'.format(epoch, HR, NDCG, ROC, loss))

        if torch.cuda.is_available():
            torch.cuda.synchronize()
        t_end = time.perf_counter()

        HR_per_run.append(HR)
        NDCG_per_run.append(NDCG)
        ROC_per_run.append(ROC)

        print('Run {}, Duration: {:.4f}, HR: {}, NDCG: {:.4f}, ROC: {:.4f} loss: {:.4f}'.format(run, t_end - t_start, HR, NDCG, ROC, loss))
    print(
        'Overall HR: {}, NDCG: {:.4f}, AUC: {:.4f}, loss: {:.4f}'.format(
            np.mean(HR_per_run), np.mean(NDCG_per_run), np.mean(ROC_per_run), np.mean(loss_per_run)
        )
    )
    save_global_logger(global_logger_path, HR_per_run, NDCG_per_run, ROC_per_run, loss_per_run)
