# -*- coding: utf-8 -*-
"""DCN_Wine_20201223.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1B9dvlEAvmmocurWPJrLbxegfALfcP59L

# DCN

## 1. Install & Import Packages
"""

!pip install -q tensorflow-recommenders
!pip install -q --upgrade tensorflow-datasets

# Commented out IPython magic to ensure Python compatibility.
import os
import pandas as pd

import tensorflow as tf

import numpy as np
import matplotlib.pyplot as plt

import pprint

# %matplotlib inline
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable

import tensorflow as tf
import tensorflow_recommenders as tfrs

from tensorflow.keras.losses import binary_crossentropy
from tensorflow.keras import backend as K
from tensorflow.keras.layers import Lambda, Input, Dense, Dropout
from tensorflow.keras.models import Model
from tensorflow.keras.callbacks import LambdaCallback, EarlyStopping, Callback
from tensorflow.keras.utils import plot_model
import glob

def get_path(filename):
  return f'drive/MyDrive/Colab Notebooks/Data/{filename}'

glob.glob("drive/MyDrive/Colab Notebooks/Data/*")

train = pd.read_json(get_path('train_all_meta_v2.json'))
test = pd.read_json(get_path('test_all_meta_v2.json'))

train.body.value_counts().sum()

"""## 2. Preprocess"""

train = train[~train.body.isna()].reset_index(drop=True)
test = test[~test.body.isna()].reset_index(drop=True)

INT_FEATURES = ["type_id", "body", "acidity", "like"]

for int_feature in INT_FEATURES:
  train[int_feature] = train[int_feature].astype(int)
  test[int_feature] = test[int_feature].astype(int)

train.country_code= train.country_code.fillna('un')
test.country_code= test.country_code.fillna('un')

train['grapes_id_unique'] = train.grapes_id.map(lambda x: x[0] if x else 0)
test['grapes_id_unique'] = test.grapes_id.map(lambda x: x[0] if x else 0)

# tf.keras.layers.experimental.preprocessing.
feature_names = ["userID", "wine_id", "country_code",  "like",
                 "type_id", "body", "acidity", "grapes_id_unique"]

for feature_name in feature_names:
  print(feature_name, train[feature_name].isna().sum())

for feature_name in feature_names:
  print(feature_name, test[feature_name].isna().sum())

str_features = ["userID", "wine_id", "country_code"]
int_features = ["type_id", "body", "acidity", "grapes_id_unique", "like"]

train_str_dict = {
    str_feature: [str(val).encode() for val in train[str_feature].values]
    for str_feature in str_features
}

train_int_dict = {
    int_feature: train[int_feature].values
    for int_feature in int_features
}

train_str_dict.update(train_int_dict)
train_str_dict.keys()

test_str_dict = {
    str_feature: [str(val).encode() for val in test[str_feature].values]
    for str_feature in str_features
}

test_int_dict = {
    int_feature: test[int_feature].values
    for int_feature in int_features
}

test_str_dict.update(test_int_dict)
test_str_dict.keys()

train = tf.data.Dataset.from_tensor_slices(train_str_dict)
test = tf.data.Dataset.from_tensor_slices(test_str_dict)

vocabularies = {}

for feature_name in feature_names:
  vocab = train.batch(1_000_000).map(lambda x: x[feature_name])
  vocabularies[feature_name] = np.unique(np.concatenate(list(vocab)))

vocabularies

"""## 3. Model"""

class DCN(tfrs.Model):

  def __init__(self, use_cross_layer, deep_layer_sizes, projection_dim=None):
    super().__init__()

    self.embedding_dimension = 32

    str_features = ["userID", "wine_id", "country_code"]
    int_features = ["type_id", "body", "acidity", "grapes_id_unique"]

    self._all_features = str_features + int_features
    self._embeddings = {}

    # Compute embeddings for string features.
    for feature_name in str_features:
      vocabulary = vocabularies[feature_name]
      self._embeddings[feature_name] = tf.keras.Sequential(
          [tf.keras.layers.experimental.preprocessing.StringLookup(
              vocabulary=vocabulary, mask_token=None),
           tf.keras.layers.Embedding(len(vocabulary) + 1,
                                     self.embedding_dimension)
    ])
      
    # Compute embeddings for int features.
    for feature_name in int_features:
      vocabulary = vocabularies[feature_name]
      self._embeddings[feature_name] = tf.keras.Sequential(
          [tf.keras.layers.experimental.preprocessing.IntegerLookup(
              vocabulary=vocabulary, mask_value=None),
           tf.keras.layers.Embedding(len(vocabulary) + 1,
                                     self.embedding_dimension)
    ])

    if use_cross_layer:
      self._cross_layer = tfrs.layers.dcn.Cross(
          projection_dim=projection_dim,
          kernel_initializer="glorot_uniform")
    else:
      self._cross_layer = None

    self._deep_layers = [tf.keras.layers.Dense(layer_size, activation="relu")
      for layer_size in deep_layer_sizes]

    self._logit_layer = tf.keras.layers.Dense(1)

    self.task = tfrs.tasks.Ranking(
      loss=tf.keras.losses.MeanSquaredError(),
      metrics=[tf.keras.metrics.RootMeanSquaredError("RMSE")]
    )

  def call(self, features):
    # Concatenate embeddings
    embeddings = []
    for feature_name in self._all_features:
      embedding_fn = self._embeddings[feature_name]
      embeddings.append(embedding_fn(features[feature_name]))

    x = tf.concat(embeddings, axis=1)

    # Build Cross Network
    if self._cross_layer is not None:
      x = self._cross_layer(x)
    
    # Build Deep Network
    for deep_layer in self._deep_layers:
      x = deep_layer(x)

    return self._logit_layer(x)

  def compute_loss(self, features, training=False):
    labels = features.pop("like")
    scores = self(features)
    return self.task(
        labels=labels,
        predictions=scores,
    )

learning_rate = 0.002

cached_train = train.shuffle(100_000).batch(8192).cache()
cached_test = test.batch(4096).cache()

model = DCN(use_cross_layer=True, deep_layer_sizes=[192, 192], projection_dim=None)
model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate))

"""## 4. Train & Result"""

from sklearn.metrics import roc_auc_score
from sklearn.metrics import classification_report
import tensorflow_datasets as tfds

cached_test_numpy = tfds.as_numpy(cached_test)
y_true = [item['like'] for item in cached_test_numpy]
y_true = np.concatenate(y_true)

def get_result(model):
  y_pred = model.predict(cached_test).flatten()
  y_pred_class = [1 if pred > 0.5 else 0 for pred in y_pred]

  print(f"ROC: {roc_auc_score(y_true, y_pred)}")
  print(classification_report(y_true, y_pred_class))

history1 = model.fit(cached_train,  epochs=10, verbose=True)

get_result(model)

history2 = model.fit(cached_train,  epochs=10, verbose=True)
get_result(model)

history3 = model.fit(cached_train,  epochs=10, verbose=True)
get_result(model)

model.summary()

mat = model._cross_layer._dense.kernel
features = model._all_features

block_norm = np.ones([len(features), len(features)])

dim = model.embedding_dimension

# Compute the norms of the blocks.
for i in range(len(features)):
  for j in range(len(features)):
    block = mat[i * dim:(i + 1) * dim,
                j * dim:(j + 1) * dim]
    block_norm[i,j] = np.linalg.norm(block, ord="fro")

plt.figure(figsize=(9,9))
im = plt.matshow(block_norm, cmap=plt.cm.Blues)
ax = plt.gca()
divider = make_axes_locatable(plt.gca())
cax = divider.append_axes("right", size="5%", pad=0.05)
plt.colorbar(im, cax=cax)
cax.tick_params(labelsize=10) 
_ = ax.set_xticklabels([""] + features, rotation=45, ha="left", fontsize=10)
_ = ax.set_yticklabels([""] + features, fontsize=10)

test.take(100).batch(100)

model

model.predict(cached_test)