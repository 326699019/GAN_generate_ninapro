from __future__ import division
import os
#import sys
import time
import math
#import argparse
import tensorflow as tf
import tensorflow.contrib.slim as slim
import numpy as np
import scipy.io as sio
from six.moves import xrange
#from PIL import Image

from ops import *

FLAG = tf.app.flags
FLAGS = FLAG.FLAGS

FLAG.DEFINE_float('learning_rate', 0.0001, 'Initial learning rate.')
FLAG.DEFINE_integer('epoch', 1000, 'Number of epochs to run trainer.')
FLAG.DEFINE_boolean('is_test', False, 'Test or not.')
FLAG.DEFINE_boolean('iwgan', False, 'Using improved wgan or not.')
FLAG.DEFINE_boolean('old_param', False, 'Saving new variables or not.')
FLAG.DEFINE_boolean('update_new', False, 'If True, only update new variables.')
FLAG.DEFINE_integer('batch_size', 1024, 'Batch size.')
FLAG.DEFINE_integer('ckpt', 1, 'Save checkpoint every ? epochs.')
FLAG.DEFINE_integer('sample', 1, 'Get sample every ? epochs.')
FLAG.DEFINE_integer('gpu', 2, 'GPU No.')

DATASET_NAME = 'nina001'
DATA_PATH = 'data/' + DATASET_NAME + '.bin'
CHECKPOINT_DIR = 'checkpoint/' + DATASET_NAME + '_new'
OLD_CHECKPOINT_DIR = 'checkpoint/mnist'
LOG_DIR = 'log/' + DATASET_NAME + '_new'
SAMPLE_DIR = 'samples/' + DATASET_NAME + '_new'

BETA1 = 0.5
BETA2 = 0.9
LAMB_GP = 10

DATA_DIM = 10
NOISE_DIM = 3


def train(sess):

    real_data_holder = tf.placeholder(
        tf.float32, [FLAGS.batch_size, DATA_DIM], name='real_data')
    input_noise_holder = tf.placeholder(
        tf.float32, [FLAGS.batch_size, NOISE_DIM], name='input_noise')

    fake_data = generator(input_noise_holder)
    real_score = discriminator(real_data_holder)
    fake_score = discriminator(fake_data, reuse=True)
    all_vars = tf.trainable_variables()
    #new_vars = [var for var in all_vars if '_new' in var.name]
    #old_vars = [var for var in all_vars if '_old' in var.name]
    if FLAGS.update_new:
        new_vars = [var for var in all_vars if '_new' in var.name]
        gene_vars = [var for var in new_vars if 'g_' in var.name]
        disc_vars = [var for var in new_vars if 'd_' in var.name]
    else:
        gene_vars = [var for var in all_vars if 'g_' in var.name]
        disc_vars = [var for var in all_vars if 'd_' in var.name]
    sampler = generator(input_noise_holder, is_train=False)
    #samples_shaped = tf.reshape(sampler, [-1, DATA_DIM, 1, 1])
    tf.summary.histogram('samples', sampler)

    if not FLAGS.iwgan:
        all_score = tf.concat([real_score, fake_score], axis=0)
        labels_gene = tf.ones([FLAGS.batch_size])
        labels_disc = tf.concat(
            [tf.ones([FLAGS.batch_size]), tf.zeros([FLAGS.batch_size])], axis=0)
        gene_loss = tf.reduce_mean(
            tf.nn.sigmoid_cross_entropy_with_logits(
                labels=labels_gene, logits=fake_score))
        disc_loss = tf.reduce_mean(
            tf.nn.sigmoid_cross_entropy_with_logits(
                labels=labels_disc, logits=all_score))

        gene_train_op = tf.train.AdamOptimizer(
            FLAGS.learning_rate, BETA1).minimize(
                gene_loss, var_list=gene_vars)
        disc_train_op = tf.train.AdamOptimizer(
            FLAGS.learning_rate, BETA1).minimize(
                disc_loss, var_list=disc_vars)
    else:
        gene_loss = -tf.reduce_mean(fake_score)
        disc_loss = tf.reduce_mean(fake_score) - tf.reduce_mean(real_score)
        alpha = tf.random_uniform(
            shape=[FLAGS.batch_size, 1, 1, 1],
            minval=0.,
            maxval=1.
        )
        differences = fake_data - real_data_holder
        interpolates = real_data_holder + (alpha * differences)
        gradients = tf.gradients(discriminator(
            interpolates, reuse=True), [interpolates])[0]
        slopes = tf.sqrt(tf.reduce_sum(
            tf.square(gradients), reduction_indices=[1]))
        gradient_penalty = tf.reduce_mean((slopes - 1.)**2)
        disc_loss += LAMB_GP * gradient_penalty

        gene_train_op = tf.train.AdamOptimizer(
            FLAGS.learning_rate, BETA1, BETA2).minimize(gene_loss, var_list=gene_vars)
        disc_train_op = tf.train.AdamOptimizer(
            FLAGS.learning_rate, BETA1, BETA2).minimize(disc_loss, var_list=disc_vars)

    tf.summary.scalar('gene_loss', gene_loss)
    tf.summary.scalar('disc_loss', disc_loss)
    merged = tf.summary.merge_all()
    writer = tf.summary.FileWriter(LOG_DIR, sess.graph)

    tf.global_variables_initializer().run()

    counter = 1
    saver = tf.train.Saver()
    if FLAGS.old_param:
        variables_to_restore = slim.get_variables_to_restore(
            include=['discriminator/d_h1_conv_old', 'discriminator/d_h1_bn_old',
                     'discriminator/d_h2_conv_old', 'discriminator/d_h2_bn_old',
                     'generator/g_h2_conv_old', 'generator/g_h2_bn_old',
                     'generator/g_h3_conv_old'])
        restore_saver = tf.train.Saver(variables_to_restore)
        could_load, checkpoint_counter = load(
            sess, restore_saver, OLD_CHECKPOINT_DIR)
    else:
        could_load, checkpoint_counter = load(
            sess, saver, CHECKPOINT_DIR)
    if could_load:
        counter = checkpoint_counter
        print ' [*] Load SUCCESS'
    else:
        print ' [!] Load failed...'


    start_time = time.time()

    if FLAGS.is_test:
        noise_batch = np.random.uniform(-1, 1,
                                        [FLAGS.batch_size, NOISE_DIM]).astype(np.float32)

        index = 0
        file_object = open(DATA_PATH, 'rb')
        for data_batch in read_in_chunks(file_object, FLAGS.batch_size):
            if data_batch.shape[0] != FLAGS.batch_size:
                break
            samples, gene_loss_value, disc_loss_value = sess.run(
                [sampler, gene_loss, disc_loss],
                feed_dict={
                    real_data_holder: data_batch,
                    input_noise_holder: noise_batch
                })
            label = 1
            repetition = index
            shape = np.array(samples.shape)
            subject = 0
            matpath = SAMPLE_DIR + '/000_001_%03d.mat' % repetition
            print label, repetition, shape, subject, matpath
            sio.savemat(matpath, {'data': samples, 'label': label,
                                  'repetition': repetition, 'shape': shape, 'subject': subject})

            print samples[:10]

            print(
                '[Sample %2d] G_loss: %.8f, D_loss: %.8f'
                % (index, gene_loss_value, disc_loss_value))
            index += 1
            if index >= FLAGS.epoch:
                break
        return

    # fixed_noise = np.random.uniform(-1, 1,
    #                                [FLAGS.batch_size, NOISE_DIM]).astype(np.float32)
    for epoch in xrange(FLAGS.epoch):
        index = 0
        file_object = open(DATA_PATH, 'rb')
        print 'Current Epoch is: ' + str(epoch)

        for data_batch in read_in_chunks(file_object, FLAGS.batch_size):
            if data_batch.shape[0] != FLAGS.batch_size:
                break
            noise_batch = np.random.uniform(-1, 1,
                                            [FLAGS.batch_size, NOISE_DIM]).astype(np.float32)

            if epoch % FLAGS.sample == 0 and index == 0:
                summary, samples, gene_loss_value, disc_loss_value = sess.run(
                    [merged, sampler, gene_loss, disc_loss],
                    feed_dict={
                        real_data_holder: data_batch,
                        input_noise_holder: noise_batch
                    })
                writer.add_summary(summary, epoch)

                print samples[:10]

                print(
                    '[Getting Sample...] G_loss: %2.8f, D_loss: %2.8f'
                    % (gene_loss_value, disc_loss_value))

            if epoch % FLAGS.ckpt == 0 and index == 0:
                save(sess, saver, CHECKPOINT_DIR, counter)

            if index % 2 == 0:
                _, gene_loss_value, disc_loss_value = sess.run(
                    [disc_train_op, gene_loss, disc_loss],
                    feed_dict={
                        real_data_holder: data_batch,
                        input_noise_holder: noise_batch
                    })

            _, gene_loss_value, disc_loss_value = sess.run(
                [gene_train_op, gene_loss, disc_loss],
                feed_dict={
                    real_data_holder: data_batch,
                    input_noise_holder: noise_batch
                })
            if index % 100 == 0:
                print(
                    'Epoch: %3d batch: %4d time: %4.2f, G_loss: %2.8f, D_loss: %2.8f'
                    % (epoch, index, time.time() - start_time, gene_loss_value,
                       disc_loss_value))
            index += 1
            counter += 1


def discriminator(data, reuse=False):
    with tf.variable_scope('discriminator') as scope:
        if reuse:
            scope.reuse_variables()

        hidden = conv2d(tf.reshape(data, [-1, 10, 1, 1]),
                        16, k_h=3, k_w=3, d_h=2, d_w=2, name='d_h1_conv_old')
        hidden = lrelu(batch_norm(hidden, name='d_h1_bn_old'))

        hidden = conv2d(hidden, 32, k_h=3, k_w=3,
                        d_h=2, d_w=2, name='d_h2_conv_old')
        hidden = lrelu(batch_norm(hidden, name='d_h2_bn_old'))

        hidden = linear(tf.reshape(
            hidden, [FLAGS.batch_size, -1]), 1, 'd_h3_fc_new')

        return hidden[:, 0]


def generator(noise, is_train=True):
    with tf.variable_scope('generator') as scope:
        if not is_train:
            scope.reuse_variables()

        hidden = linear(noise, NOISE_DIM * 1 * 32, 'g_h1_fc_new')
        hidden = tf.nn.relu(batch_norm(
            hidden, train=is_train, name='g_h1_bn_new'))
        hidden = tf.reshape(hidden, [-1, NOISE_DIM, 1, 32])

        hidden = deconv2d(hidden, [FLAGS.batch_size, 6, 1, 16],
                          k_h=3, k_w=3, d_h=2, d_w=2, name='g_h2_conv_old')
        hidden = tf.nn.relu(batch_norm(
            hidden, train=is_train, name='g_h2_bn_old'))

        hidden = deconv2d(hidden, [FLAGS.batch_size, 12, 1, 1],
                          k_h=3, k_w=3, d_h=2, d_w=2, name='g_h3_conv_old')
        hidden = tf.nn.sigmoid(hidden)

        hidden = tf.maximum(0.0024, hidden)
        hidden = tf.reshape(hidden, [-1, 12])

        return hidden[:, 1:11]


def save(sess, saver, checkpoint_dir, step):
    model_name = "model"

    if not os.path.exists(checkpoint_dir):
        os.makedirs(checkpoint_dir)

    saver.save(
        sess, os.path.join(checkpoint_dir, model_name), global_step=step)


def load(sess, saver, checkpoint_dir):
    import re
    print ' [*] Reading checkpoints...'

    ckpt = tf.train.get_checkpoint_state(checkpoint_dir)
    if ckpt and ckpt.model_checkpoint_path:
        ckpt_name = os.path.basename(ckpt.model_checkpoint_path)
        saver.restore(sess, os.path.join(checkpoint_dir, ckpt_name))
        counter = int(next(re.finditer("(\d+)(?!.*\d)", ckpt_name)).group(0))
        print " [*] Success to read {}".format(ckpt_name)
        return True, counter
    else:
        print ' [*] Failed to find a checkpoint'
        return False, 0


def read_in_chunks(file_object, chunk_size):
    while True:
        size = DATA_DIM
        batch = np.fromfile(
            file_object, dtype=np.uint8, count=size * chunk_size)
        if batch is None:
            break
        data = np.reshape(batch, (-1, DATA_DIM))
        yield data


def combine_images(images):
    num = images.shape[0]
    width = int(math.sqrt(num))
    height = int(math.ceil(float(num) / width))
    shape = images.shape[1:4]
    output_image = np.zeros(
        (height * shape[0], width * shape[1], shape[2]),
        dtype=images.dtype)
    for index, img in enumerate(images):
        i = int(index / width)
        j = index % width
        output_image[i * shape[0]:(i + 1) * shape[0], j * shape[1]:(j + 1) * shape[1], :] = \
            img[:, :, :]
    return output_image


"""
def save_all_data(epoch, index, input_image):
    image = combine_images(input_image)
    image = image * 127.5 + 127.5

    if FLAGS.is_test:
        image_path = SAMPLE_DIR + "_test/" + \
            str(epoch) + "_" + str(index) + ".png"
    else:
        image_path = SAMPLE_DIR + "/" + str(epoch) + "_" + str(index) + ".png"
    if IMAGE_DIM == 1:
        image = np.squeeze(image)
        Image.fromarray(image.astype(np.uint8), mode='L').save(image_path)
    else:
        Image.fromarray(image.astype(np.uint8)).save(image_path)
"""


def main(_):

    print 'learning_rate is: ' + str(FLAGS.learning_rate)
    print 'epoch is:         ' + str(FLAGS.epoch)
    print 'is_test is:       ' + str(FLAGS.is_test)
    print 'iwgan is:         ' + str(FLAGS.iwgan)
    print 'old_param is:      ' + str(FLAGS.old_param)
    print 'batch_size is:    ' + str(FLAGS.batch_size)
    print 'ckpt is:          ' + str(FLAGS.ckpt)
    print 'sample is:        ' + str(FLAGS.sample)
    print 'gpu is:           ' + str(FLAGS.gpu)

    if not os.path.exists(CHECKPOINT_DIR):
        os.makedirs(CHECKPOINT_DIR)
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)
    if not os.path.exists(SAMPLE_DIR):
        os.makedirs(SAMPLE_DIR)

    run_config = tf.ConfigProto(allow_soft_placement=True)
    run_config.gpu_options.allow_growth = True
    with tf.device('/gpu:' + str(FLAGS.gpu)):
        with tf.Session(config=run_config) as sess:
            train(sess)


if __name__ == '__main__':
    tf.app.run()
