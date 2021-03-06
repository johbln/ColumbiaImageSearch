import json
import time
import multiprocessing
from .generic_kafka_processor import GenericKafkaProcessor
from ..imgio.imgio import buffer_to_B64

default_prefix = "KIP_"
default_prefix_frompkl = "KIPFP_"

# TODO: This class should be rewritten to actually extract features from images...
# TODO: Work on getting a pycaffe sentibank featurizer. Check we get same feature values than command line in 'sentibank_cmdline'
# at 'https://github.com/ColumbiaDVMM/ColumbiaImageSearch/blob/master/cu_image_search/feature_extractor/sentibank_cmdline.py'
# Should we have a generic extractor to inherit from, with just a different process_one_core() method?...

class KafkaImageProcessor(GenericKafkaProcessor):

  def __init__(self, global_conf_filename, prefix=default_prefix, pid=None):
    # when running as deamon
    self.pid = pid
    # call GenericKafkaProcessor init (and others potentially)
    super(KafkaImageProcessor, self).__init__(global_conf_filename, prefix)
    # any additional initialization needed, like producer specific output logic
    self.cdr_out_topic = self.get_required_param('producer_cdr_out_topic')
    self.images_out_topic = self.get_required_param('producer_images_out_topic')
    # TODO: get s3 url prefix from actual location
    # for now "object_stored_prefix" in "_meta" of domain CDR
    # but just get from conf
    self.url_prefix = self.get_required_param('obj_stored_prefix')
    self.process_count = 0
    self.process_failed = 0
    self.process_time = 0
    self.set_pp()

  def set_pp(self):
    self.pp = "KafkaImageProcessor"
    if self.pid:
      self.pp += ":"+str(self.pid)



  def process_one(self, msg):
    from ..imgio.imgio import get_SHA1_img_info_from_buffer, get_buffer_from_URL

    self.print_stats(msg)

    msg_value = json.loads(msg.value)

    # From msg value get list_urls for image objects only
    list_urls = self.get_images_urls(msg_value)

    # Get images data and infos
    dict_imgs = dict()
    for url, obj_pos in list_urls:
      start_process = time.time()
      if self.verbose > 2:
        print_msg = "[{}.process_one: info] Downloading image from: {}"
        print print_msg.format(self.pp, url)
      try:
        img_buffer = get_buffer_from_URL(url)
        if img_buffer:
          sha1, img_type, width, height = get_SHA1_img_info_from_buffer(img_buffer)
          dict_imgs[url] = {'obj_pos': obj_pos, 'img_buffer': img_buffer, 'sha1': sha1, 'img_info': {'format': img_type, 'width': width, 'height': height}}
          self.toc_process_ok(start_process)
        else:
          self.toc_process_failed(start_process)
          if self.verbose > 1:
            print_msg = "[{}.process_one: info] Could not download image from: {}"
            print print_msg.format(self.pp, url)
      except Exception as inst:
        self.toc_process_failed(start_process)
        if self.verbose > 0:
          print_msg = "[{}.process_one: error] Could not download image from: {} ({})"
          print print_msg.format(self.pp, url, inst)

    # Push to cdr_out_topic
    self.producer.send(self.cdr_out_topic, self.build_cdr_msg(msg_value, dict_imgs))

    # TODO: we could have all extraction registered here, and not pushing an image if it has been processed by all extractions. But that violates the consumer design of Kafka...
    # Push to images_out_topic
    for img_out_msg in self.build_image_msg(dict_imgs):
      self.producer.send(self.images_out_topic, img_out_msg)


class KafkaImageProcessorFromPkl(GenericKafkaProcessor):
  # To push list of images to be processed from a pickle file containing a dictionary
  # {'update_ids': update['update_ids'], 'update_images': out_update_images}
  # with 'out_update_images' being a list of tuples (sha1, url)

  def __init__(self, global_conf_filename, prefix=default_prefix_frompkl):
    # call GenericKafkaProcessor init (and others potentially)
    super(KafkaImageProcessorFromPkl, self).__init__(global_conf_filename, prefix)
    # any additional initialization needed, like producer specific output logic
    self.images_out_topic = self.get_required_param('images_out_topic')
    self.pkl_path = self.get_required_param('pkl_path')
    self.process_count = 0
    self.process_failed = 0
    self.process_time = 0
    self.display_count = 100
    self.set_pp()

  def set_pp(self):
    self.pp = "KafkaImageProcessorFromPkl"

  def get_next_img(self):
    import pickle
    update = pickle.load(open(self.pkl_path,'rb'))
    for sha1, url in update['update_images']:
      yield sha1, url

  def build_image_msg(self, dict_imgs):
    # Build dict ouput for each image with fields 's3_url', 'sha1', 'img_info' and 'img_buffer'
    img_out_msgs = []
    for url in dict_imgs:
      tmp_dict_out = dict()
      tmp_dict_out['s3_url'] = url
      tmp_dict_out['sha1'] = dict_imgs[url]['sha1']
      tmp_dict_out['img_info'] = dict_imgs[url]['img_info']
      # encode buffer in B64?
      tmp_dict_out['img_buffer'] = buffer_to_B64(dict_imgs[url]['img_buffer'])
      img_out_msgs.append(json.dumps(tmp_dict_out).encode('utf-8'))
    return img_out_msgs

  def process(self):
    from ..imgio.imgio import get_SHA1_img_info_from_buffer, get_buffer_from_URL

    # Get images data and infos
    for sha1, url in self.get_next_img():

      if (self.process_count + self.process_failed) % self.display_count == 0:
        avg_process_time = self.process_time / max(1, self.process_count + self.process_failed)
        print_msg = "[%s] dl count: %d, failed: %d, time: %f"
        print print_msg % (self.pp, self.process_count, self.process_failed, avg_process_time)

      dict_imgs = dict()
      start_process = time.time()
      if self.verbose > 2:
        print_msg = "[{}.process_one: info] Downloading image from: {}"
        print print_msg.format(self.pp, url)
      try:
        img_buffer = get_buffer_from_URL(url)
        if img_buffer:
          sha1, img_type, width, height = get_SHA1_img_info_from_buffer(img_buffer)
          dict_imgs[url] = {'img_buffer': img_buffer, 'sha1': sha1,
                            'img_info': {'format': img_type, 'width': width, 'height': height}}
          self.toc_process_ok(start_process)
        else:
          self.toc_process_failed(start_process)
          if self.verbose > 1:
            print_msg = "[{}.process_one: info] Could not download image from: {}"
            print print_msg.format(self.pp, url)
      except Exception as inst:
        self.toc_process_failed(start_process)
        if self.verbose > 0:
          print_msg = "[{}.process_one: error] Could not download image from: {} ({})"
          print print_msg.format(self.pp, url, inst)

      # Push to images_out_topic
      for img_out_msg in self.build_image_msg(dict_imgs):
        self.producer.send(self.images_out_topic, img_out_msg)

class DaemonKafkaImageProcessor(multiprocessing.Process):

  daemon = True

  def __init__(self, conf, prefix=default_prefix):
    super(DaemonKafkaImageProcessor, self).__init__()
    self.conf = conf
    self.prefix = prefix

  def run(self):
    try:
      print "Starting worker KafkaImageProcessor.{}".format(self.pid)
      kp = KafkaImageProcessor(self.conf, prefix=self.prefix, pid=self.pid)
      for msg in kp.consumer:
        kp.process_one(msg)
    except Exception as inst:
      print "KafkaImageProcessor.{} died ()".format(self.pid, inst)