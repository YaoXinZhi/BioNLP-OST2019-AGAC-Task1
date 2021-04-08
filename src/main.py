# -*- coding:utf-8 -*-
# ! usr/bin/env python3
"""
Created on 07/04/2021 12:53
@Author: XINZHI YAO
"""

import os
import logging
import os
import random
import numpy as np

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset

from transformers import BertTokenizerFast, BertModel, BertTokenizer

from TorchCRF import CRF

from tensorboardX import SummaryWriter

# from src.model import BERT_CRF, BertCRFTagger
# from src.utils import *
# from src.dataloader import SeqLabeling_Dataset
# from src.config import args
#
from model import BERT_CRF, BertCRFTagger
from utils import *
from dataloader import SeqLabeling_Dataset
from config import args

from seqeval.metrics import f1_score
from seqeval.metrics import precision_score
from seqeval.metrics import accuracy_score
from seqeval.metrics import recall_score
from seqeval.metrics import classification_report


def evaluation(model, data_loader, index_to_label, vocab_dict, paras):
    model.eval()

    total_pred_label = []
    total_ture_label = []
    with torch.no_grad():
        for step, batch in enumerate(data_loader):
            batch_data, batch_label = batch
            batch_data_list = [data.split('&&&') for data in batch_data]
            batch_label_list = [label.split('&&&') for label in batch_label]

            input_ids, mask = batch_data_processing(batch_data_list, paras.max_length,
                                                            vocab_dict.get('[PAD]'),
                                                            vocab_dict.get('[CLS]'),
                                                            vocab_dict.get('[SEP]'))

            input_ids = input_ids.to(device)
            mask = mask.to(device)

            batch_max_length = input_ids.shape[1]

            predict_result = model(input_ids, mask)

            predict_label_list = convert_index_to_label(predict_result, index_to_label)
            ture_label_list = label_truncation(batch_label_list, batch_max_length)

            logger.debug('Example:')
            logger.debug(f'predict: {predict_label_list[0]}')
            logger.debug(f'ture: {ture_label_list[0]}')

            for predict_list, ture_list in zip(predict_label_list, ture_label_list):
                if len(predict_list) != len(ture_list):
                    logger.debug('different length.')
                    logger.debug(f'predict: {len(predict_list)}, ture: {len(ture_list)}')
                    logger.debug(f'{predict_list}\n{ture_list}')
                    continue
                total_pred_label.append(predict_list)
                total_ture_label.append(ture_list)


    # logger.debug(f'{total_ture_label}\n{total_pred_label}')
    logger.debug(f'total ture_label: {len(total_ture_label)}, '
                 f'total pred_label: {len(total_pred_label)}')

    acc = accuracy_score(total_ture_label, total_pred_label)
    precision = precision_score(total_ture_label, total_pred_label)
    recall = recall_score(total_ture_label, total_pred_label)
    f1 = f1_score(total_ture_label, total_pred_label)

    return acc, precision, recall, f1



def main(paras):

    logger = logging.getLogger(__name__)
    if args.save_log_file:
        logging.basicConfig(format = '%(asctime)s - %(levelname)s - %(name)s -   %(message)s',
                            datefmt = '%m/%d/%Y %H:%M:%S',
                            level = logging.DEBUG,
                            filename=paras.log_file,
                            filemode='w')
    else:
        logging.basicConfig(format = '%(asctime)s - %(levelname)s - %(name)s -   %(message)s',
                            datefmt = '%m/%d/%Y %H:%M:%S',
                            level = logging.DEBUG,)


    device = 'cuda' if torch.cuda.is_available() else 'cpu'

    logger.info(f'Loading model: {paras.model_name}.')
    tokenizer = BertTokenizerFast.from_pretrained(paras.model_name)
    bert = BertModel.from_pretrained(paras.model_name, output_hidden_states=True)

    vocab_dict = tokenizer.get_vocab()

    # train dataset
    train_dataset = SeqLabeling_Dataset(paras.train_data, paras.label_file, vocab_dict)
    label_to_index = train_dataset.label_to_index
    index_to_label = train_dataset.index_to_label

    train_dataloader = DataLoader(train_dataset, batch_size=paras.batch_size,
                                  shuffle=paras.shuffle, drop_last=paras.drop_last)

    # test dataset
    test_dataset = SeqLabeling_Dataset(paras.test_data, paras.label_file, vocab_dict)
    test_dataloader = DataLoader(test_dataset, batch_size=paras.batch_size,
                                 shuffle=paras.shuffle, drop_last=paras.drop_last)


    bert_crf_tagger = BertCRFTagger(bert, paras.hidden_size, paras.num_tags,
                                paras.droupout_prob).to(device)

    optimizer = torch.optim.Adam(bert_crf_tagger.parameters(), lr=paras.learning_rate)


    # train
    best_loss = 0
    for epoch in range(paras.num_train_epochs):
        epoch_loss = 0
        bert_crf_tagger.train()
        for step, batch in enumerate(train_dataloader):
            optimizer.zero_grad()

            batch_data, batch_label = batch
            batch_data_list = [ data.split('&&&') for data in batch_data ]
            batch_label_list = [ label.split('&&&') for label in batch_label ]

            input_ids, mask = batch_data_processing(batch_data_list, paras.max_length,
                                                            vocab_dict.get('[PAD]'),
                                                            vocab_dict.get('[CLS]'),
                                                            vocab_dict.get('[SEP]'))

            input_ids = input_ids.to(device)
            mask = mask.to(device)

            # break
            # encoded_input = tokenizer(batch_data_list,
            #                           return_offsets_mapping=True,
            #                           max_length=paras.max_length,
            #                           truncation=True,
            #                           is_split_into_words=True,
            #                           padding=True,
            #                           return_tensors='pt').to(device)

            # input_ids = encoded_input['input_ids']
            # mask = encoded_input['attention_mask'].byte()

            batch_max_length = input_ids.shape[1]
            batch_label_pad = label_padding(batch_max_length, batch_label_list,
                                            label_to_index)

            batch_label_pad = torch.LongTensor(batch_label_pad)

            loss = bert_crf_tagger(input_ids, mask, batch_label_pad)

            epoch_loss += loss.detach().cpu().item()

            logger.info(f'epoch: {epoch}, step: {step}, loss: {loss:.4f}')
            # acc, precision, recall, f1 = evaluation(bert_crf_tagger, test_dataloader,
            #                                         index_to_label, tokenizer, paras)
            # logger.info(f'ACC.: {acc:.4f}, Precision: {precision:.4f}, '
            #             f'Recall: {recall:.4f}, F1-score: {f1:.4f}')

            loss.backward()
            optimizer.step()

        epoch_loss = epoch_loss / len(train_dataloader)

        acc, precision, recall, f1 = evaluation(bert_crf_tagger, test_dataloader,
                                                index_to_label, vocab_dict, paras)

        if best_loss == 0 or epoch_loss < best_loss:
            best_loss = epoch_loss
            torch.save(bert_crf_tagger, paras.model_save_path)
            logger.info(f'update model, best loss: {best_loss:.4f}')

        logger.info(f'Epoch: {epoch}, Loss: {epoch_loss}')
        logger.info(f'ACC.: {acc:.4f}, Precision: {precision:.4f}, '
              f'Recall: {recall:.4f}, F1-score: {f1:.4f}')



if __name__ == '__main__':

    args = args()
    # paras = args()

    main(args)


