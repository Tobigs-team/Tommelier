# -*- coding: utf-8 -*-
"""DeepFM_class.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1kKcuBre0P7Lazm3meoKlfo_tJthFn4qc
"""

# Commented out IPython magic to ensure Python compatibility.
from google.colab import drive
drive.mount('/content/drive')

# %cd /content/drive/My Drive/Tobigs/컨퍼런스_와인추천/

import pandas as pd
import numpy as np
from sklearn.preprocessing import MultiLabelBinarizer
from itertools import repeat
from sklearn.preprocessing import MinMaxScaler
import tensorflow as tf
from time import perf_counter
from sklearn.metrics import accuracy_score, roc_auc_score, precision_score
import itertools
import matplotlib.pyplot as plt

train_df = pd.read_json('Data_최종본/train_all_meta_v2.json')
test_df = pd.read_json('Data_최종본/test_all_meta_v2.json')

X_train = train_df.loc[:,['rating_count','rating_average','body','acidity','alcohol','food','winery_ratings_count','winery_ratings_average','user_follower_count','user_following_count','user_rating_count']]
y_train = train_df['like']
X_test = test_df.loc[:,['rating_count','rating_average','body','acidity','alcohol','food','winery_ratings_count','winery_ratings_average','user_follower_count','user_following_count','user_rating_count']]
y_test = test_df['like']

ALL_FIELDS = X_train.columns
CAT_FIELDS = ['food']
CONT_FIELDS = list(set(ALL_FIELDS).difference(CAT_FIELDS))

# Parameters
BATCH_SIZE = 256
EMBEDDING_SIZE = 1
EPOCHS = 20


"""class에 알맞게 전처리"""

# X_train field에 맞춰 modify
field_dict = dict()
field_index = []
X_modified = pd.DataFrame()

for index, col in enumerate(X_train.columns):
    
    # if col in DUMMY_FIELDS:
    #     type_id = pd.get_dummies(X_train[col], prefix=col, prefix_sep='-')
    #     field_dict[index] = list(type_id.columns)
    #     field_index.extend(repeat(index, type_id.shape[1]))
    #     X_modified = pd.concat([X_modified, type_id], axis=1)

    if col in CAT_FIELDS:
        one_hot = MultiLabelBinarizer()
        X_cat_col = pd.DataFrame(one_hot.fit_transform(X_train[col].fillna('None')), columns=one_hot.classes_)
        field_dict[index] = list(X_cat_col.columns)
        field_index.extend(repeat(index, X_cat_col.shape[1]))
        X_modified = pd.concat([X_modified, X_cat_col], axis=1)

    if col in CONT_FIELDS:
        scaler = MinMaxScaler()
        X_cont_col = pd.DataFrame(scaler.fit_transform(X_train[[col]]), columns=[col])
        field_dict[index] = col
        field_index.append(index)
        X_modified = pd.concat([X_modified, X_cont_col], axis=1)


X_train_modified = X_modified

# X_test field에 맞춰 modify
field_dict = dict()
field_index = []
X_modified = pd.DataFrame()

for index, col in enumerate(X_test.columns):

    # if col in DUMMY_FIELDS:
    #     type_id = pd.get_dummies(X_test[col], prefix=col, prefix_sep='-')
    #     field_dict[index] = list(type_id.columns)
    #     field_index.extend(repeat(index, type_id.shape[1]))
    #     X_modified = pd.concat([X_modified, type_id], axis=1)

    if col in CAT_FIELDS:
        one_hot = MultiLabelBinarizer()
        X_cat_col = pd.DataFrame(one_hot.fit_transform(X_test[col].fillna('None')), columns=one_hot.classes_)
        field_dict[index] = list(X_cat_col.columns)
        field_index.extend(repeat(index, X_cat_col.shape[1]))
        X_modified = pd.concat([X_modified, X_cat_col], axis=1)

    if col in CONT_FIELDS:
        scaler = MinMaxScaler()
        X_cont_col = pd.DataFrame(scaler.fit_transform(X_test[[col]]), columns=[col])
        field_dict[index] = col
        field_index.append(index)
        X_modified = pd.concat([X_modified, X_cont_col], axis=1)


X_test_modified = X_modified

# 결측 mean으로 fillna
for col in X_train_modified:
    if X_train_modified[col].isnull().sum():
        X_train_modified[col].fillna(X_train_modified[col].mean(), inplace=True)

for col in X_test_modified:
    if X_test_modified[col].isnull().sum():
        X_test_modified[col].fillna(X_test_modified[col].mean(), inplace=True)



"""class 구현"""

class FM_layer(tf.keras.layers.Layer):
    def __init__(self, num_feature, num_field, embedding_size, field_index):
        super(FM_layer, self).__init__()
        self.embedding_size = embedding_size    # k: 임베딩 벡터의 차원(크기)
        self.num_feature = num_feature          # f: 원래 feature 개수
        self.num_field = num_field              # m: grouped field 개수
        self.field_index = field_index          # 인코딩된 X의 칼럼들이 본래 어디 소속이었는지

        # Parameters of FM Layer
        # w: capture 1st order interactions
        # V: capture 2nd order interactions
        self.w = tf.Variable(tf.random.normal(shape=[num_feature],
                                              mean=0.0, stddev=1.0), name='w')
        self.V = tf.Variable(tf.random.normal(shape=(num_field, embedding_size),
                                              mean=0.0, stddev=0.01), name='V')

    def call(self, inputs):
        x_batch = tf.reshape(inputs, [-1, self.num_feature, 1])  # inputs:(256, 38), x_batch:(256, 38, 1)
        # Parameter V를 field_index에 맞게 복사하여 num_feature에 맞게 늘림
        embeds = tf.nn.embedding_lookup(params=self.V, ids=self.field_index)  # V:(14, 5), embeds:(38, 5)

        # Deep Component에서 쓸 Input
        # (batch_size, num_feature, embedding_size)
        new_inputs = tf.math.multiply(x_batch, embeds) # (256, 38, 5)

        # (batch_size, )
        linear_terms = tf.reduce_sum(
            tf.math.multiply(self.w, inputs), axis=1, keepdims=False)

        # (batch_size, )
        interactions = 0.5 * tf.subtract(
            tf.square(tf.reduce_sum(new_inputs, [1, 2])),
            tf.reduce_sum(tf.square(new_inputs), [1, 2])
        )

        linear_terms = tf.reshape(linear_terms, [-1, 1])
        interactions = tf.reshape(interactions, [-1, 1])

        y_fm = tf.concat([linear_terms, interactions], 1) # (256, 2)

        return y_fm, new_inputs

class DeepFM(tf.keras.Model):

    def __init__(self, num_feature, num_field, embedding_size, field_index):
        super(DeepFM, self).__init__()
        self.embedding_size = embedding_size    # k: 임베딩 벡터의 차원(크기)
        self.num_feature = num_feature          # f: 원래 feature 개수
        self.num_field = num_field              # m: grouped field 개수
        self.field_index = field_index          # 인코딩된 X의 칼럼들이 본래 어디 소속이었는지

        self.fm_layer = FM_layer(num_feature, num_field, embedding_size, field_index)

        self.layers1 = tf.keras.layers.Dense(units=64, activation='relu')
        self.dropout1 = tf.keras.layers.Dropout(rate=0.2)
        self.layers2 = tf.keras.layers.Dense(units=16, activation='relu')
        self.dropout2 = tf.keras.layers.Dropout(rate=0.2)
        self.layers3 = tf.keras.layers.Dense(units=2, activation='relu')

        self.final = tf.keras.layers.Dense(units=1, activation='sigmoid')

    def __repr__(self):
        return "DeepFM Model: #Field: {}, #Feature: {}, ES: {}".format(
            self.num_field, self.num_feature, self.embedding_size)

    def call(self, inputs):
        # 1) FM Component: (num_batch, 2)
        y_fm, new_inputs = self.fm_layer(inputs)

        # retrieve Dense Vectors: (num_batch, num_feature*embedding_size)
        new_inputs = tf.reshape(new_inputs, [-1, self.num_feature*self.embedding_size])

        # 2) Deep Component
        y_deep = self.layers1(new_inputs)
        y_deep = self.dropout1(y_deep)
        y_deep = self.layers2(y_deep)
        y_deep = self.dropout2(y_deep)
        y_deep = self.layers3(y_deep)

        # Concatenation
        y_pred = tf.concat([y_fm, y_deep], 1)
        y_pred = self.final(y_pred)
        y_pred = tf.reshape(y_pred, [-1, ])

        return y_pred

# Batch 나눈 dataset  --> BATCH_SIZE 변경할 경우 해당 셀 다시 돌려줘야 함
train_ds = tf.data.Dataset.from_tensor_slices(
    (tf.cast(X_train_modified.values, tf.float32), tf.cast(y_train, tf.float32))) \
    .shuffle(30000).batch(BATCH_SIZE)

test_ds = tf.data.Dataset.from_tensor_slices(
    (tf.cast(X_test_modified.values, tf.float32), tf.cast(y_test, tf.float32))) \
    .shuffle(10000).batch(BATCH_SIZE)


"""
features : item meta (user meta X) & type_id (continuous) + food (categorical)
"""

# Batch 단위 학습
def train_on_batch(model, optimizer,inputs, targets):
    with tf.GradientTape() as tape:
        y_pred = model(inputs)
        # y_pred = tf.where(tf.math.is_nan(y_pred), tf.zeros_like(y_pred), y_pred)
        loss = tf.keras.losses.binary_crossentropy(from_logits=False, y_true=targets, y_pred=y_pred)

    grads = tape.gradient(target=loss, sources=model.trainable_variables)

    # apply_gradients()를 통해 processed gradients를 적용함
    optimizer.apply_gradients(zip(grads, model.trainable_variables))

    return model


# 반복 학습 함수
def train(epochs):
    model = DeepFM(embedding_size=EMBEDDING_SIZE, num_feature=len(field_index),
                   num_field=len(field_dict), field_index=field_index)

    optimizer = tf.keras.optimizers.SGD(learning_rate=0.1)

    print("Start Training: Batch Size: {}, Embedding Size: {}".format(BATCH_SIZE, EMBEDDING_SIZE))
    
    for i in range(epochs):
        for x, y in train_ds:
            model = train_on_batch(model, optimizer, x, y)

    return model


# if __name__ == '__main__':
#     train(epochs=EPOCHS)


# sklearn metrics
start = perf_counter()
model = train(EPOCHS)
y_pred = model(X_test_modified.values).numpy().round()
# y_pred = tf.where(tf.math.is_nan(y_pred), tf.zeros_like(y_pred), y_pred)
test_acc = accuracy_score(y_test.values, y_pred)
test_auc = roc_auc_score(y_test.values, y_pred)
test_prec = precision_score(y_test.values, y_pred)

print("테스트 ACC: {:.4f}, AUC: {:.4f}, PREC: {:.4f}".format(test_acc, test_auc, test_prec))
print("걸린 시간: {:.3f}".format(perf_counter() - start))
# model.save_weights('weights/weights-epoch({})-batch({})-embedding({}).h5'.format(
    # epochs, BATCH_SIZE, EMBEDDING_SIZE))





"""###input user id에게 와인 추천

모델 학습
"""

# Batch 단위 학습
def train_on_batch(model, optimizer,inputs, targets):
    with tf.GradientTape() as tape:
        y_pred = model(inputs)
        # y_pred = tf.where(tf.math.is_nan(y_pred), tf.zeros_like(y_pred), y_pred)
        loss = tf.keras.losses.binary_crossentropy(from_logits=False, y_true=targets, y_pred=y_pred)

    grads = tape.gradient(target=loss, sources=model.trainable_variables)

    # apply_gradients()를 통해 processed gradients를 적용함
    optimizer.apply_gradients(zip(grads, model.trainable_variables))

    return model


# 반복 학습 함수
def train(epochs):
    model = DeepFM(embedding_size=EMBEDDING_SIZE, num_feature=len(field_index),
                   num_field=len(field_dict), field_index=field_index)

    optimizer = tf.keras.optimizers.Adam()

    print("Start Training: Batch Size: {}, Embedding Size: {}".format(BATCH_SIZE, EMBEDDING_SIZE))
    
    for i in range(epochs):
        for x, y in train_ds:
            model = train_on_batch(model, optimizer, x, y)

    return model


"""features : user & item meta (continuous) + food (categorical)"""

# sklearn metrics
model = train(EPOCHS)
y_pred = model(tf.cast(X_test_modified.values, tf.float64)).numpy().round()
# y_pred = tf.where(tf.math.is_nan(y_pred), tf.zeros_like(y_pred), y_pred)
test_acc = accuracy_score(y_test.values, y_pred)
test_auc = roc_auc_score(y_test.values, y_pred)
test_prec = precision_score(y_test.values, y_pred)

print("테스트 ACC: {:.4f}, AUC: {:.4f}, PREC: {:.4f}".format(test_acc, test_auc, test_prec))


"""input user에게 top K개 와인 추천"""

all_user_meta = pd.concat([train_df.userID, X_train_modified[X_train_modified.columns[-5:]]], axis=1).drop_duplicates()
all_item_meta = pd.concat([train_df.wine_id, X_train_modified[X_train_modified.columns[:-5]]], axis=1).drop_duplicates()

input_user = 1201  # 추천해줄 유저 id
input_user_meta = all_user_meta.loc[all_user_meta.userID == input_user,:].values[0][1:]
input_all = pd.DataFrame(columns=X_train_modified.columns)
for item in all_item_meta.values:
    tmp = np.concatenate((item[1:], input_user_meta))
    input_all = input_all.append(pd.Series(tmp, index=X_train_modified.columns, name=item[0]))

y_pred = model(input_all.values).numpy()
y_pred = pd.Series(y_pred, name='y_pred')
wine_id = all_item_meta.wine_id.reset_index(drop=True)
input_predict = pd.concat([wine_id, y_pred], axis=1)
input_predict = input_predict.sort_values(by='y_pred', ascending=False)

K = 50
predict_top_k = input_predict.wine_id[:K].values
predict_top_k

interact_wine_id = train_df.loc[train_df.userID==input_user,['wine_id','like']].wine_id.values
like_wine_id = train_df.loc[(train_df.userID==input_user) & (train_df.like==1),['wine_id','like']].wine_id.values  # 유저가 실제로 좋아한 wine id
like_wine_id

set(predict_top_k).intersection(like_wine_id)  # 추천해준 wine_id 중 실제 유저가 좋아한 와인



all_user_meta = pd.concat([train_df.userID, X_train_modified[X_train_modified.columns[-5:]]], axis=1).drop_duplicates().reset_index(drop=True)
all_item_meta = pd.concat([train_df.wine_id, X_train_modified[X_train_modified.columns[:-5]]], axis=1).drop_duplicates().reset_index(drop=True)

# 전체 user id 예측 -> 실제 좋아한 와인 예측 건수
wine_id = all_item_meta.wine_id.reset_index(drop=True)
K = 50
recommend_top_list = []
true_recommend = []

for input_user in all_user_meta.userID:
    
    input_user_meta = pd.DataFrame(itertools.repeat(all_user_meta.loc[all_user_meta.userID == input_user,:].values[0][1:], len(all_item_meta)), columns=X_train_modified.columns[-5:])
    input_all = pd.concat([all_item_meta.iloc[:,1:], input_user_meta], axis=1)

    y_pred = model(input_all.values).numpy()
    y_pred = pd.Series(y_pred, name='y_pred')
    input_predict = pd.concat([wine_id, y_pred], axis=1)
    input_predict = input_predict.sort_values(by='y_pred', ascending=False)
    predict_top_k = input_predict.wine_id[:K].values

    recommend_top_list.append(predict_top_k)
    like_wine_id = train_df.loc[(train_df.userID==input_user) & (train_df.like==1),'wine_id'].values
    true_recommend.append(len(set(predict_top_k).intersection(like_wine_id)))

pd.Series(true_recommend).value_counts()

"""대부분 유저가 실제로 좋아한 와인은 추천해주지 않는다."""



