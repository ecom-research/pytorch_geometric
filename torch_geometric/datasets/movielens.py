import torch
from os.path import join
from os.path import isfile
import numpy as np
import random as rd
import tqdm
import itertools
from collections import Counter

from torch_geometric.data import InMemoryDataset, download_url
from torch_geometric.io import read_ml
from torch_geometric.data import Data, extract_zip


def save_df(df, path):
    df.to_csv(path, encoding='utf-8')


def reindex_df(users, items, interactions):
    """
    reindex users, items, interactions in case there are some values missing in between
    :param users: pd.DataFrame
    :param items: pd.DataFrame
    :param interactions: pd.DataFrame
    :return: same
    """
    num_users = users.shape[0]
    num_movies = items.shape[0]

    raw_uids = np.array(users.uid, dtype=np.int)
    raw_iids = np.array(items.iid, dtype=np.int)
    uids = np.arange(num_users)
    iids = np.arange(num_movies)

    users['uid'] = uids
    items['iid'] = iids

    raw_uid2uid = {raw_uid: uid for raw_uid, uid in zip(raw_uids, uids)}
    raw_iid2iid = {raw_iid: iid for raw_iid, iid in zip(raw_iids, iids)}

    rating_uids = np.array(interactions.uid, dtype=np.int)
    rating_iids = np.array(interactions.iid, dtype=np.int)
    print('reindex user id of ratings...')
    rating_uids = [raw_uid2uid[rating_uid] for rating_uid in rating_uids]
    print('reindex item id of ratings...')
    rating_iids = [raw_iid2iid[rating_iid] for rating_iid in rating_iids]
    interactions['uid'] = rating_uids
    interactions['iid'] = rating_iids

    return users, items, interactions


def split_train_test_pos_neg_map(ratings, train_rating_idx, test_rating_mask, e2nid):
    uids = ratings.uid.unique()
    iids = ratings.iid.unique()

    pos_nid_iid_map = {uid: list(set(ratings[ratings.uid.isin([uid])].iid)) for uid in uids}
    neg_nid_iid_map = {uid: list(set(iids) - set(pos_iids)) for uid, pos_iids in pos_nid_iid_map.items()}

    train_ratings = ratings.iloc[train_rating_idx]
    test_ratings = ratings.iloc[test_rating_mask]
    train_pos_nid_iid_map = {uid: list(set(train_ratings[train_ratings.uid.isin([uid])].iid)) for uid in train_ratings.uid.unique()}
    test_pos_nid_iid_map = {uid: list(set(test_ratings[test_ratings.uid.isin([uid])].iid)) for uid in test_ratings.uid.unique()}

    train_pos_unid_inid_map = {e2nid['uid'][uid]: [e2nid['iid'][iid] for iid in iids] for uid, iids in train_pos_nid_iid_map.items()}
    test_pos_unid_inid_map = {e2nid['uid'][uid]: [e2nid['iid'][iid] for iid in iids] for uid, iids in test_pos_nid_iid_map.items()}
    neg_unid_inid_map = {e2nid['uid'][uid]: [e2nid['iid'][iid] for iid in iids] for uid, iids in neg_nid_iid_map.items()}

    return train_pos_unid_inid_map, test_pos_unid_inid_map, neg_unid_inid_map


def drop_infrequent_concept_from_str(df, concept_name, num_occs):
    def filter_concept_str(concept_str):
        return ', '.join([single_concept.split(' (')[0] for single_concept in concept_str.split(', ')])
    concept_strs = [filter_concept_str(concept_str) for concept_str in df[concept_name]]
    duplicated_concept = [concept_str.split(', ') for concept_str in concept_strs]
    duplicated_concept = list(itertools.chain.from_iterable(duplicated_concept))
    writer_counter_dict = Counter(duplicated_concept)
    del writer_counter_dict['']
    unique_concept = [k for k, v in writer_counter_dict.items() if v > num_occs]
    concept_strs = [
        ', '.join([concept for concept in concept_str.split(', ') if concept in unique_concept])
        for concept_str in concept_strs
    ]
    df[concept_name] = concept_strs
    return df


def convert_2_data(
        users, items, ratings,
        train_ratio, randomizer,
        directed
):
    """
    Entitiy node include (gender, occupation, genres)
    num_nodes = num_users + num_items + num_genders + num_occupation + num_ages + num_genres + num_years + num_directors + num_actors + num_writers
    """
    def get_concept_num_from_str(df, concept_name):
        concept_strs = [concept_str.split(', ') for concept_str in df[concept_name]]
        concepts = set(itertools.chain.from_iterable(concept_strs))
        concepts.remove('')
        num_concepts = len(concepts)
        return list(concepts), num_concepts

    num_users = users.shape[0]
    num_items = items.shape[0]

    #########################  Define relationship  #########################
    relations = [
        'gender2u2user', 'occupation2user', 'age2user', 'genre2item', 'year2item',
        'director2item', 'actor2item', 'writer2item', 'user2item',
    ]

    #########################  Define entities  #########################
    genders = ['M', 'F']
    num_genders = len(genders)

    occupations = list(users.occupation.unique())
    num_occupations = len(occupations)

    ages = list(users.age.unique())
    num_ages = len(ages)

    genres = list(items.keys()[4:21])
    num_genres = len(genres)

    years = list(items.discretized_year.unique())
    num_years = len(years)

    directors, num_directors = get_concept_num_from_str(items, 'directors')
    actors, num_actors = get_concept_num_from_str(items, 'actors')
    writers, num_writers = get_concept_num_from_str(items, 'writers')

    #########################  Define number of entities  #########################
    num_nodes = num_users + num_items + num_genders + num_occupations + num_ages + num_genres + num_years + \
                num_directors + num_actors + num_writers

    #########################  Define entities to node id map  #########################
    acc = 0
    uid2nid = {uid: i + acc for i, uid in enumerate(users['uid'])}
    nid2e = {i + acc: ('uid', uid) for i, uid in enumerate(users['uid'])}
    acc += users.shape[0]
    iid2nid = {iid: i + acc for i, iid in enumerate(items['iid'])}
    for i, iid in enumerate(items['iid']):
        nid2e[i + acc] = ('iid', iid)
    acc += items.shape[0]
    gender2nid = {gender: i + acc for i, gender in enumerate(genders)}
    for i, gender in enumerate(genders):
        nid2e[i + acc] = ('gender', gender)
    acc += num_genders
    occ2nid = {occupation: i + acc for i, occupation in enumerate(occupations)}
    for i, occ in enumerate(occupations):
        nid2e[i + acc] = ('occ', occ)
    acc += num_occupations
    age2nid = {age: i + acc for i, age in enumerate(ages)}
    for i, age in enumerate(ages):
        nid2e[i + acc] = ('age', age)
    acc += num_ages
    genre2nid = {genre: i + acc for i, genre in enumerate(genres)}
    for i, genre in enumerate(genres):
        nid2e[i + acc] = ('genre', genre)
    acc += num_genres
    year2nid = {year: i + acc for i, year in enumerate(years)}
    for i, year in enumerate(years):
        nid2e[i + acc] = ('year', year)
    acc += num_years
    director2nid = {director: i + acc for i, director in enumerate(directors)}
    for i, director in enumerate(directors):
        nid2e[i + acc] = ('director', director)
    acc += num_directors
    actor2nid = {actor: i + acc for i, actor in enumerate(actors)}
    for i, actor in enumerate(actors):
        nid2e[i + acc] = ('actor', actor)
    acc += num_actors
    writer2nid = {writer: i + acc for i, writer in enumerate(writers)}
    for i, writer in enumerate(writers):
        nid2e[i + acc] = ('writer', writer)
    e2nid = {'uid': uid2nid, 'iid': iid2nid, 'gender': gender2nid, 'occ': occ2nid, 'age': age2nid, 'genre': genre2nid,
             'year': year2nid, 'director': director2nid, 'actor': actor2nid, 'writer': writer2nid}

    #########################  create graphs  #########################
    u_nids = [e2nid['uid'][uid] for uid in users.uid]
    gender_nids = [e2nid['gender'][gender] for gender in users.gender]
    occ_nids = [e2nid['occ'][occ] for occ in users.occ]
    age_nids = [e2nid['age'][age] for age in users.age]

    print('Creating item property edges...')
    i_nids = [e2nid['iid'][iid] for iid in items.iid]
    y_nids = [e2nid['year'][year] for year in items.discretized_year]
    directors = [directors.split(',') for directors in items.directors]
    actors = items.actors
    writers = items.writers

    print('Creating rating property edges...')
    u_nids = [e2nid['uid'][uid] for uid in ratings.uid]
    i_nids = [e2nid['iid'][iid] for iid in ratings.iid]

    kwargs = {
        'num_nodes': num_nodes,
        'users': users, 'ratings': ratings, 'items': items,
        'relations': relations,
        'e2nid': e2nid, 'nid2e': nid2e
    }

    if train_ratio is not None:
        train_rating_mask = torch.zeros(ratings.shape[0], dtype=torch.bool)
        test_rating_mask = torch.ones(ratings.shape[0], dtype=torch.bool)
        train_rating_idx = randomizer.choices(range(ratings.shape[0]), k=int(ratings.shape[0] * train_ratio))
        train_rating_mask[train_rating_idx] = 1
        test_rating_mask[train_rating_idx] = 0

        if directed:
            train_edge_mask = torch.cat(
                (
                    torch.ones(rating_begin, dtype=torch.bool),
                    train_rating_mask,
                    train_rating_mask)
            )

            test_edge_mask = torch.cat(
                (
                    torch.zeros(rating_begin, dtype=torch.bool),
                    test_rating_mask,
                    test_rating_mask)
            )
        else:
            train_edge_mask = torch.cat(
                (
                    torch.ones(rating_begin, dtype=torch.bool),
                    train_rating_mask,
                    torch.ones(rating_begin, dtype=torch.bool),
                    train_rating_mask)
            )

            test_edge_mask = torch.cat(
                (
                    torch.zeros(rating_begin, dtype=torch.bool),
                    test_rating_mask,
                    torch.zeros(rating_begin, dtype=torch.bool),
                    test_rating_mask)
            )
        kwargs['train_edge_mask'] = train_edge_mask
        kwargs['test_edge_mask'] = test_edge_mask

        train_pos_unid_inid_map, test_pos_unid_inid_map, neg_unid_inid_map = \
            split_train_test_pos_neg_map(ratings, train_rating_idx, test_rating_mask, e2nid)
        kwargs['train_pos_unid_inid_map'], kwargs['test_pos_unid_inid_map'], kwargs['neg_unid_inid_map'] = \
            train_pos_unid_inid_map, test_pos_unid_inid_map, neg_unid_inid_map

    return Data(**kwargs)


class MovieLens(InMemoryDataset):
    url = 'http://files.grouplens.org/datasets/movielens/'

    def __init__(self,
                 root,
                 name,
                 transform=None,
                 pre_transform=None,
                 pre_filter=None,
                 **kwargs):
        self.name = name.lower()
        assert self.name in ['1m']
        self.num_core = kwargs.get('num_core', 10)
        self.num_feat_core = kwargs.get('num_feat_core', 10)
        self.implicit = kwargs.get('implicit', True)
        self.train_ratio = kwargs.get('train_ratio', None)
        self.debug = kwargs.get('debug', None)
        self.seed = kwargs.get('seed', None)
        self.randomizer = rd.Random() if self.seed is None else rd.Random(self.seed)
        self.directed = kwargs.get('directed', True)
        self.suffix = self.build_suffix()
        super(MovieLens, self).__init__(root, transform, pre_transform, pre_filter)

        self.data, self.slices = torch.load(self.processed_paths[0])
        if self.implicit:
            self.data.edge_attr[self.data.rating_edge_mask[0], 1] = 1
        print('Graph params: {}'.format(self.data))

        print('Dataset loaded!')

    @property
    def raw_file_names(self):
        return 'ml-{}.zip'.format(self.name.lower())

    @property
    def processed_file_names(self):
        return ['data{}.pt'.format(self.suffix)]

    def download(self):
        path = download_url(self.url + self.raw_file_names, self.raw_dir)
        extract_zip(path, self.raw_dir)

    def process(self):
        unzip_raw_dir = join(self.raw_dir, 'ml-{}'.format(self.name))

        # read files
        if isfile(join(self.processed_dir, 'movies.pkl')) and isfile(join(self.processed_dir, 'ratings.pkl')) and isfile(join(self.processed_dir, 'users.pkl')):
            print('Read data frame!')
            users, items, ratings = read_ml(self.processed_dir, processed=True)
            users = users.fillna('')
            items = items.fillna('')
            ratings = ratings.fillna('')
        else:
            print('Read from raw data!')
            users, items, ratings = read_ml(unzip_raw_dir, processed=False)

            # Discretized year
            years = items.year.to_numpy()
            min_year = min(years)
            max_year = max(years)
            num_years = (max_year - min_year) // 10
            discretized_years = [min_year + i * 10 for i in range(num_years + 1)]
            for i, year in enumerate(discretized_years):
                if i == 0:
                    years[years <= year] = year
                else:
                    years[(years <= year) & (years > discretized_years[i - 1])] = year
            items['discretized_year'] = years

            # remove duplications
            users = users.drop_duplicates()
            items = items.drop_duplicates()
            ratings = ratings.drop_duplicates()

            # Compute the movie and user counts
            item_count = ratings['iid'].value_counts()
            user_count = ratings['uid'].value_counts()
            item_count.name = 'movie_count'
            user_count.name = 'user_count'
            ratings = ratings.join(item_count, on='iid')
            ratings = ratings.join(user_count, on='uid')

            # Remove infrequent users and item in ratings
            ratings = ratings[ratings.movie_count > self.num_core]
            ratings = ratings[ratings.user_count > self.num_core]

            # Sync the user and item dataframe
            users = users[users.uid.isin(ratings['uid'])]
            items = items[items.iid.isin(ratings['iid'])]

            # Drop the infrequent writer, actor and directors
            items = drop_infrequent_concept_from_str(items, 'writers', self.num_feat_core)
            items = drop_infrequent_concept_from_str(items, 'directors', self.num_feat_core)
            items = drop_infrequent_concept_from_str(items, 'actors', self.num_feat_core)

            users, items, ratings = reindex_df(users, items, ratings)
            save_df(users, join(self.processed_dir, 'users.pkl'))
            save_df(items, join(self.processed_dir, 'movies.pkl'
                                                    ''))
            save_df(ratings, join(self.processed_dir, 'ratings.pkl'))

        if self.debug is not None:
            ratings = ratings.iloc[self.randomizer.choices(range(ratings.shape[0]), k=int(self.debug * ratings.shape[0]))]
            users = users[users.uid.isin(ratings.uid)]
            items = items[items.iid.isin(ratings.iid)]

        data = convert_2_data(users, items, ratings, self.train_ratio, self.randomizer, self.directed)

        torch.save(self.collate([data]), self.processed_paths[0], pickle_protocol=4)

    def __repr__(self):
        return '{}-{}'.format(self.__class__.__name__, self.name.capitalize())

    def build_suffix(self):
        suffixes = []
        if self.directed:
            suffixes.append('directed_')
        suffixes.append('core_{}'.format(self.num_core))
        suffixes.append('featcore_{}'.format(self.num_feat_core))
        if self.train_ratio is not None:
            suffixes.append('train_{}'.format(self.train_ratio))
        if self.seed is not None:
            suffixes.append('seed_{}'.format(self.seed))
        if self.debug is not None:
            suffixes.append('debug_{}'.format(self.debug))
        if not suffixes:
            suffix = ''
        else:
            suffix = '_'.join(suffixes)
        return '_' + suffix


if __name__ == '__main__':
    import os.path as osp
    root = osp.join('.', 'tmp', 'ml')
    name = '1m'
    debug = 0.01
    seed = 2020
    dataset = MovieLens(root=root, name='1m', debug=debug, train_ratio=0.8, seed=seed)
    print('stop')

