import torch
from movie.engine import Engine
from movie.utils import use_cuda
from movie.feature2embedding import Feature2Embedding

class GMF(torch.nn.Module):
    def __init__(self, config):
        super(GMF, self).__init__()
        self.num_users = config['num_users']
        self.num_items = config['num_items']
        self.latent_dim = config['latent_dim']

        self.embedding_user_model = Feature2Embedding(input_size=config['num_features'], output_size=self.latent_dim)
        self.embedding_item = torch.nn.Embedding(num_embeddings=self.num_items, embedding_dim=self.latent_dim)

        self.affine_output = torch.nn.Linear(in_features=self.latent_dim, out_features=1)
        self.logistic = torch.nn.Sigmoid()

    def forward(self, user_features, item_indices):
        user_embedding = self.embedding_user_model(user_features)
        item_embedding = self.embedding_item(item_indices)
        element_product = torch.mul(user_embedding, item_embedding)
        logits = self.affine_output(element_product)
        rating = self.logistic(logits)
        return rating

    def init_weight(self):
        pass

class GMFWrapper(GMF):
    def forward(self, features):
        user_dict, item_dict, user_indices, item_indices, user_features, id2index = features.getData()
        c = torch.zeros(1, len(item_dict), len(user_dict))
        user_embedding = self.embedding_user_model(user_features)
        item_embedding = self.embedding_item(torch.LongTensor([id2index[x.item()] for x in item_indices]))
        element_product = torch.mul(user_embedding, item_embedding)
        logits = self.affine_output(element_product)
        logits = (logits - torch.mean(logits)) / (torch.std(logits) + 1e-5)
        ratings = self.logistic(logits)
        for user_id, item_id, rating in zip(user_indices, item_indices, ratings):
            c[0, item_dict[item_id.item()], user_dict[user_id.item()]] = rating
        return c

class GMFEngine(Engine):
    """Engine for training & evaluating GMF model"""
    def __init__(self, config):
        self.model = GMF(config)
        if config['use_cuda'] is True:
            use_cuda(True, config['device_id'])
            self.model.cuda()
        super(GMFEngine, self).__init__(config)
