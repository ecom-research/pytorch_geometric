import torch
from os.path import join
import numpy as np
import random as rd
import tqdm
import pickle
import pandas as pd


from torch_geometric.data import InMemoryDataset, download_url
from torch_geometric.io import read_lastfm
from torch_geometric.data import Data, extract_zip
from torch_geometric.utils import get_sec_order_edge


def reindex_df(
        raw_uids, raw_aids, raw_tids,
        artists, tags, user_artists, bi_user_friends):
    """

    :param uids:
    :param aids:
    :param tids:
    :param artists:
    :param tags:
    :param user_artists:
    :param user_taggedartists:
    :param bi_user_friends:
    :return:
    """
    uids = np.arange(raw_uids.shape[0])
    aids = np.arange(raw_aids.shape[0])
    tids = np.arange(raw_tids.shape[0])

    raw_uid2uid = {raw_uid: uid for raw_uid, uid in zip(raw_uids, uids)}
    raw_aid2aid = {raw_aid: aid for raw_aid, aid in zip(raw_aids, aids)}
    raw_tid2tid = {raw_tid: tid for raw_tid, tid in zip(raw_tids, tids)}
    raw_tid2tid[np.nan] = np.nan

    print('reindex artist index of artists...')
    artists_aids = np.array(artists.aid, dtype=np.int)
    artists_tids = np.array(artists.tid, dtype=np.float)
    artists_aids = [raw_aid2aid[aid] for aid in artists_aids]
    artists_tids = [raw_tid2tid[tid] for tid in artists_tids]
    import pdb
    pdb.set_trace()
    artists.loc[:, 'aid'] = artists_aids
    artists.loc[:, 'tid'] = artists_tids

    print('reindex tag index of tags...')
    tags_tids = np.array(tags.tid.shape[0], dtype=np.int)
    tags_tids = [raw_tid2tid[tid] for tid in tags_tids]
    tags.loc[:, 'tid'] = tags_tids

    print('reindex user and artist index of user_artists...')
    user_artists_uids = np.array(user_artists.tid.shape[0], dtype=np.int)
    user_artists_aids = np.array(user_artists.aid.shape[0], dtype=np.int)
    user_artists_tids = np.array(user_artists.tid.shape[0], dtype=np.int)
    user_artists_uids = [raw_uid2uid[uid] for uid in user_artists_uids]
    user_artists_aids = [raw_aid2aid[aid] for aid in user_artists_aids]
    user_artists_tids = [raw_tid2tid[tig] for tig in user_artists_tids]
    user_artists.loc[:, 'uid'] = user_artists_uids
    user_artists.loc[:, 'aid'] = user_artists_aids
    user_artists.loc[:, 'tid'] = user_artists_tids

    print('reindex user and friends index of bi_user_friends...')
    bi_user_friends_uids = np.array(bi_user_friends.uid.shape[0], dtype=np.int)
    bi_user_friends_fids = np.array(bi_user_friends.fid.shape[0], dtype=np.int)
    bi_user_friends_uids = [raw_uid2uid[uid] for uid in bi_user_friends_uids]
    bi_user_friends_fids = [raw_uid2uid[fid] for fid in bi_user_friends_fids]
    bi_user_friends.loc[:, 'uid'] = bi_user_friends_uids
    bi_user_friends.loc[:, 'fid'] = bi_user_friends_fids
    return artists, tags, user_artists, bi_user_friends


def convert_2_data(
        artists, tags, user_artists, user_taggedartists, bi_user_friends,
        train_ratio, sec_order):
    """
    Entitiy node include (gender, occupation, genres)

    n_nodes = n_users + n_items + n_genders + n_occupation + n_ages + n_genres

    """
    n_users = users.shape[0]
    n_items = items.shape[0]

    genders = ['M', 'F']
    n_genders = len(genders)

    occupations = list(users.occupation.unique())
    n_occupations = len(occupations)

    ages = ['1', '18', '25', '35', '45', '50', '56']
    n_ages = len(ages)

    genres = list(items.keys()[3:21])
    n_genres = len(genres)

    # Bulid node id
    num_nodes = n_users + n_items + n_genders + n_occupations + n_ages + n_genres

    # Build property2id map
    users['node_id'] = users['uid']
    items['node_id'] = items['iid'] + n_users
    user_node_id_map = {uid: i for i, uid in enumerate(users['uid'].values)}
    item_node_id_map = {iid: n_users + i for i, iid in enumerate(items['iid'].values)}
    gender_node_id_map = {gender: n_users + n_items + i for i, gender in enumerate(genders)}
    occupation_node_id_map = {occupation: n_users + n_items + n_genders + i for i, occupation in enumerate(occupations)}
    genre_node_id_map = {genre: n_users + n_items + n_genders + n_occupations + i for i, genre in enumerate(genres)}
    age_node_id_map = {genre: n_users + n_items + n_genders + n_occupations + n_ages + i for i, genre in enumerate(ages)}

    # Start creating edges
    row_idx, col_idx = [], []
    edge_attrs = []

    rating_begin = 0

    print('Creating user property edges...')
    for _, row in tqdm.tqdm(users.iterrows(), total=users.shape[0]):
        gender = row['gender']
        occupation = row['occupation']
        age = row['age']

        u_nid = row['uid']
        gender_nid = gender_node_id_map[gender]
        row_idx.append(u_nid)
        col_idx.append(gender_nid)

        occupation_nid = occupation_node_id_map[occupation]
        row_idx.append(u_nid)
        col_idx.append(occupation_nid)

        age_nid = age_node_id_map[age]
        row_idx.append(u_nid)
        col_idx.append(age_nid)
    edge_attrs += [-1 for i in range(3 * users.shape[0])]
    rating_begin += 3 * users.shape[0]

    print('Creating item property edges...')
    for _, row in tqdm.tqdm(items.iterrows(), total=items.shape[0]):
        i_nid = item_node_id_map[row['iid']]

        for genre in genres:
            if not row[genre]:
                continue
            g_nid = genre_node_id_map[genre]
            row_idx.append(i_nid)
            col_idx.append(g_nid)
            edge_attrs.append(-1)
            rating_begin += 1

    print('Creating rating property edges...')
    row_idx += list(users.iloc[ratings['uid']]['node_id'].values)
    col_idx += list(items.iloc[ratings['iid']]['node_id'].values)
    edge_attrs += list(ratings['rating'])

    print('Building masks...')
    rating_mask = torch.ones(ratings.shape[0], dtype=torch.bool)
    rating_edge_mask = torch.cat(
        (
            torch.zeros(rating_begin, dtype=torch.bool),
            rating_mask,
            torch.zeros(rating_begin, dtype=torch.bool),
            rating_mask),
    )
    if train_ratio is not None:
        train_rating_mask = torch.zeros(ratings.shape[0], dtype=torch.bool)
        test_rating_mask = torch.ones(ratings.shape[0], dtype=torch.bool)
        train_rating_idx = rd.sample([i for i in range(ratings.shape[0])], int(ratings.shape[0] * train_ratio))
        train_rating_mask[train_rating_idx] = 1
        test_rating_mask[train_rating_idx] = 0

        train_edge_mask = torch.cat(
            (
                torch.ones(rating_begin, dtype=torch.bool),
                train_rating_mask,
                torch.ones(rating_begin, dtype=torch.bool),
                train_rating_mask)
        )

        test_edge_mask = torch.cat(
            (
                torch.ones(rating_begin, dtype=torch.bool),
                test_rating_mask,
                torch.ones(rating_begin, dtype=torch.bool),
                test_rating_mask)
        )

    print('Creating reverse user property edges...')
    for _, row in tqdm.tqdm(users.iterrows(), total=users.shape[0]):
        gender = row['gender']
        occupation = row['occupation']
        age = row['age']

        u_nid = row['uid']
        gender_nid = gender_node_id_map[gender]
        col_idx.append(u_nid)
        row_idx.append(gender_nid)

        occupation_nid = occupation_node_id_map[occupation]
        col_idx.append(u_nid)
        row_idx.append(occupation_nid)

        age_nid = age_node_id_map[age]
        col_idx.append(u_nid)
        row_idx.append(age_nid)
    edge_attrs += [-1 for i in range(3 * users.shape[0])]

    print('Creating reverse item property edges...')
    for _, row in tqdm.tqdm(items.iterrows(), total=items.shape[0]):
        i_nid = item_node_id_map[row['iid']]

        for genre in genres:
            if not row[genre]:
                continue
            g_nid = genre_node_id_map[genre]
            col_idx.append(i_nid)
            row_idx.append(g_nid)
            edge_attrs.append(-1)

    print('Creating reverse rating property edges...')
    col_idx += list(users.iloc[ratings['uid']]['node_id'].values)
    row_idx += list(items.iloc[ratings['iid']]['node_id'].values)
    edge_attrs += list(ratings['rating'])

    row_idx = [int(idx) for idx in row_idx]
    col_idx = [int(idx) for idx in col_idx]
    row_idx = np.array(row_idx).reshape(1, -1)
    col_idx = np.array(col_idx).reshape(1, -1)
    edge_index = np.concatenate((row_idx, col_idx), axis=0)
    edge_index = torch.from_numpy(edge_index).long()
    edge_attrs = np.array(edge_attrs)
    edge_attrs = torch.from_numpy(edge_attrs).long().t()

    kwargs = {
        'num_nodes': num_nodes,
        'edge_index': edge_index, 'edge_attr': edge_attrs,
        'rating_edge_mask': rating_edge_mask,
        'users': users, 'ratings': ratings, 'items': items,
        'user_node_id_map': user_node_id_map,
        'gender_node_id_map': gender_node_id_map, 'occupation_node_id_map': occupation_node_id_map,
        'age_node_id_map': age_node_id_map, 'genre_node_id_map': genre_node_id_map
    }

    if train_ratio is not None:
        kwargs['train_edge_mask'] = train_edge_mask
        kwargs['test_edge_mask'] = test_edge_mask
        if sec_order:
            print('Creating second order edges...')
            kwargs['train_sec_order_edge_index'] = \
                get_sec_order_edge(edge_index[:, train_edge_mask])
            kwargs['n_sec_order_edge'] = kwargs['train_sec_order_edge_index'].shape[1]
    else:
        if sec_order:
            print('Creating second order edges...')
            kwargs['sec_order_edge_index'] = get_sec_order_edge(edge_index)
            kwargs['n_sec_order_edge'] = kwargs['sec_order_edge_index'].shape[1]

    return Data(**kwargs)


def save(obj, path):
    with open(path, 'wb') as f:
        pickle.dump(obj, f)


def restore(path):
    with open(path, 'rb') as f:
        obj = pickle.load(f)
    return obj


class LastFM(InMemoryDataset):
    url = 'http://files.grouplens.org/datasets/hetrec2011/'

    def __init__(self,
                 root,
                 name,
                 sec_order=False,
                 num_cores=10,
                 num_tag_cores=10,
                 transform=None,
                 pre_transform=None,
                 pre_filter=None,
                 **kwargs):
        self.name = name.lower()
        assert self.name in ['2k']
        self.num_cores = num_cores
        self.num_tag_cores = num_tag_cores
        self.sec_order = sec_order

        self.train_ratio = kwargs.get('train_ratio', None)
        self.debug = kwargs.get('debug', False)
        self.seed = kwargs.get('seed', None)
        self.suffix = self.build_suffix()
        super(LastFM, self).__init__(root, transform, pre_transform, pre_filter)

        self.data, self.slices = torch.load(self.processed_paths[0])
        print('Graph params: {}'.format(self.data))

        print('Dataset loaded!')

    @property
    def raw_file_names(self):
        return 'hetrec2011-lastfm-{}.zip'.format(self.name.lower())

    @property
    def processed_file_names(self):
        return ['data{}.pt'.format(self.suffix)]

    def download(self):
        path = download_url(self.url + self.raw_file_names, self.raw_dir)

        extract_zip(path, self.raw_dir)

    def process(self):
        unzip_raw_dir = self.raw_dir

        # read files
        artists, tags, user_artists, user_taggedartists, bi_user_friends = read_lastfm(unzip_raw_dir, self.debug)

        # remove duplications
        artists = artists.drop_duplicates()
        tags = tags.drop_duplicates()
        user_artists = user_artists.drop_duplicates()
        user_taggedartists = user_taggedartists.drop_duplicates()
        bi_user_friends = bi_user_friends.drop_duplicates()

        # Remove the interactions less than num_cores, and rebuild users and artists df
        user_artists = user_artists[user_artists.listen_count > self.num_cores]
        uids = user_artists.uid.drop_duplicates().sort_values()
        aids = user_artists.aid.drop_duplicates().sort_values()

        # Remove the artists not in aids
        artists = artists[artists.aid.isin(aids)]

        # Remove the users not in uids
        bi_user_friends = bi_user_friends[bi_user_friends.uid.isin(uids) & bi_user_friends.fid.isin(uids)]
        bi_user_friends = bi_user_friends[bi_user_friends.uid != bi_user_friends.fid]

        # Remove the sparse tags from tags and user_taggedartists dataframe
        tag_count = user_taggedartists.tid.value_counts()
        tag_count.name = 'tag_count'
        user_taggedartists = user_taggedartists.join(tag_count, on='tid')
        user_taggedartists = user_taggedartists[user_taggedartists.tag_count > self.num_tag_cores]
        user_taggedartists = user_taggedartists[user_taggedartists.uid.isin(uids) & user_taggedartists.aid.isin(aids)]
        tids = user_taggedartists.tid.drop_duplicates().sort_values()
        tags = tags[tags.tid.isin(tids)]

        # Remove tags not in user_taggedartists
        artists = pd.merge(artists, user_taggedartists[['aid', 'tid']], on='aid', how='outer')

        artists, tags, user_artists, bi_user_friends = \
            reindex_df(uids, aids, tids, artists, tags, user_artists, bi_user_friends)

        # data = convert_2_data(
        #     artists, tags, user_artists, user_taggedartists, bi_user_friends,
        #     self.train_ratio, self.sec_order
        # )

        torch.save(self.collate([data]), self.processed_paths[0], pickle_protocol=4)

    def __repr__(self):
        return '{}-{}'.format(self.__class__.__name__, self.name.capitalize())

    def build_suffix(self):
        suffixes = []
        if self.train_ratio is not None:
            suffixes.append('train_{}'.format(self.train_ratio))
        if self.debug:
            suffixes.append('debug_{}'.format(self.debug))
        if self.sec_order:
            suffixes.append('sec_order')
        if self.seed is not None:
            suffixes.append('seed_{}'.format(self.seed))
        if not suffixes:
            suffix = ''
        else:
            suffix = '_'.join(suffixes)
        return '_' + suffix


if __name__ == '__main__':
    import torch
    from torch_geometric.datasets import MovieLens
    import os.path as osp

    torch.random.manual_seed(2019)

    emb_dim = 300
    repr_dim = 64
    batch_size = 128

    root = osp.join('.', 'tmp', 'lastfm')
    dataset = LastFM(root, '2k')
    data = dataset.data
