# Application of Time2Feat on real dataset
import pickle
import time
import numpy as np
import pandas as pd

import sys
sys.path.append("../..")

from t2f.extraction.extractor import feature_extraction
from t2f.model.clustering import ClusterWrapper
from t2f.data.dataset import read_ucr_datasets
from t2f.selection.selection import cleaning
from sklearn.model_selection import train_test_split
from sklearn.metrics import adjusted_mutual_info_score
import os
import warnings
warnings.filterwarnings("ignore")

from sb3_contrib.common.maskable.utils import get_action_masks

from sklearn.metrics import davies_bouldin_score, calinski_harabasz_score, silhouette_score
from jqmcvi.base import dunn_fast

from normalization import ZScoreNormalization, MinMaxNormalization
from early_stopping import PlateauEarlyStopping

from rl.environments.feature_selection_env import FeatureSelectionEnv
from rl.agents.ql_agent import QLAgent
from rl.agents.knn_td_agent import KNNTDAgent

from tqdm import tqdm


if __name__ == '__main__':
    dataset_names = ['BasicMotions', 'Libras', 'ERing', 'RacketSports']
    transform_type = 'minmax'
    model_type = 'Hierarchical'
    train_size = 0.3
    batch_size = 500
    p = os.cpu_count()

    # silhouette_norm = ZScoreNormalization(silhouette_score, name='silhouette')
    # calinski_norm = ZScoreNormalization(calinski_harabasz_score, name='calinski_harabasz')

    silhouette_norm = ZScoreNormalization(
        score_function=silhouette_score,
        name='silhouette',
    )
    
    calinski_norm = ZScoreNormalization(
        score_function=calinski_harabasz_score,
        name='calinski_harabasz',
    )

    davies_bouldin_norm = ZScoreNormalization(
        score_function=davies_bouldin_score,
        maximize=False,  # minimum score is zero, with lower values indicating better clustering
        name='davies_bouldin',
    )

    dunn_index_norm = ZScoreNormalization(
        score_function=dunn_fast,
        name='dunn_index',
    )
    
    normalized_scorers = [
        silhouette_norm,
        calinski_norm,
        davies_bouldin_norm,
        dunn_index_norm
    ]

    for nameDataset in dataset_names:
        print(f'Dataset: {nameDataset}')
        extract_time = 0
        ts_list, y_true = read_ucr_datasets(nameDataset=nameDataset)
        n_clusters = len(set(y_true))  # Get number of clusters to find

        # Create cluster model
        model = ClusterWrapper(n_clusters=n_clusters, model_type=model_type, transform_type=transform_type)
        print('Dataset shape: {}, Num of clusters: {}'.format(ts_list.shape, n_clusters))

        # This side is dedicated for the Semi-Supervised
        labels = {}
        if train_size > 0:
            # Extract a subset of labelled mts to train the semi-supervised model
            idx_train, _, y_train, _ = train_test_split(
                np.arange(len(ts_list)), y_true, train_size=train_size)
            labels = {i: j for i, j in zip(idx_train, y_train)}
            # print('Number of Labels: {}'.format(len(labels)))

        if not os.path.isfile("../../data/"+nameDataset+"_feats.pkl"):
            time_start = time.time()
            df_all_feats = feature_extraction(ts_list, batch_size, p)
            extract_time = time.time() - time_start
            file = open("../../data/"+nameDataset+"_feats.pkl", 'wb')
            pickle.dump(df_all_feats, file)

        with open("../../data/"+nameDataset+"_feats.pkl", 'rb') as pickle_file:
            df_all_feats = pickle.load(pickle_file)

        df_all_feats = cleaning(df_all_feats)
        print('Number of features:', len(df_all_feats.columns))

        total_number_of_features = [50]
        episodes_total = [50]

        print('Total number of features:', total_number_of_features)
        for n_features in total_number_of_features:
            if n_features > len(df_all_feats.columns):
                n_features = len(df_all_feats.columns) - 1

        results = None
        
        for k in [1, 3, 9]:
            print(f'k: {k}')
            for alpha in [0.1, 0.001, 0.0001]:
                print(f'alpha: {alpha}')
                for decay_episodes in [10, 20, 30]:
                    print(f'decay_episodes: {decay_episodes}')
                    start_time = time.time()
                    env = FeatureSelectionEnv(
                        df_features=df_all_feats,
                        n_features=n_features,
                        clustering_model=model,
                        normalized_scorers=normalized_scorers,
                        early_stopping=PlateauEarlyStopping(
                            patience=20,
                            plateau_patience=20,
                            threshold=0.03
                        )
                    )
                    obs = env.reset()
                    done = False
                    runs = 3
                    for run in range(runs):
                        for episodes in episodes_total:
                            agent = KNNTDAgent(
                                starting_state=tuple(obs),
                                state_space=env.observation_space,
                                action_space=env.action_space,
                                k=k,
                                alpha=alpha,
                                gamma=1.0,
                                initial_epsilon=1.0,
                                min_epsilon=0.05,
                                decay_episodes=decay_episodes
                            )

                            y_pred = y_true

                            for episode in tqdm(range(episodes)):
                                # print(f'Episode: {episode}')
                                rewards = []
                                features = []
                                while not done:
                                    action_masks = get_action_masks(env)
                                    action = agent.act(action_masks=action_masks, episode=episode)
                                    # print('Action:', action)
                                    next_obs, reward, done, info = env.step(action)
                                    # print(next_obs)
                                    features_selected = info['features_selected']
                                    features.append(' | '.join(features_selected))
                                    agent.learn(tuple(next_obs), reward, done)
                                    rewards.append(reward)
                                
                                finTime = (time.time() - start_time) + extract_time

                                y_pred = model.fit_predict(df_all_feats[features_selected])
                                AMI = adjusted_mutual_info_score(y_pred, y_true)
                                    
                                new_results = pd.DataFrame({
                                    'k': k,
                                    'alpha': alpha,
                                    'decay_episodes': decay_episodes,
                                    'run': run,
                                    'episode': episode,
                                    'rewards': rewards,
                                    'features': features,
                                    'y_pred': str(y_pred),
                                    'scores': env.scores_received,
                                    'AMI': AMI,
                                    'time': finTime,
                                    **env.real_scores,
                                    **env.normalized_scores,
                                })
                                '''if results is None:
                                    results = new_results.copy()
                                else:
                                    results = pd.concat([results, new_results])'''

                                # Append the DataFrame to the CSV file
                                new_results.to_csv(f"results/knn_results_{nameDataset}.csv", mode='a', index=False)
                                new_results.to_json(f"results/knn_results_{nameDataset}.json", orient='records')
                                # print(env.current_state)
                                obs = env.reset()
                                done = False

        results.to_csv(f'results/knn_results_{nameDataset}.csv', index=False)
