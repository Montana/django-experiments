from django.utils.functional import cached_property

from redis.exceptions import ConnectionError, ResponseError

from experiments.redis_client import get_redis_client


COUNTER_CACHE_KEY = 'experiments:participants:%s'
COUNTER_FREQ_CACHE_KEY = 'experiments:freq:%s'


class Counters(object):

    @cached_property
    def _redis(self):
        return get_redis_client()

    def increment(self, key, participant_identifier, count=1):
        if count == 0:
            return

        try:
            cache_key = COUNTER_CACHE_KEY % key
            freq_cache_key = COUNTER_FREQ_CACHE_KEY % key
            new_value = self._redis.hincrby(cache_key, participant_identifier, count)

            # Maintain histogram of per-user counts
            if new_value > count:
                self._redis.hincrby(freq_cache_key, new_value - count, -1)
            self._redis.hincrby(freq_cache_key, new_value, 1)
        except (ConnectionError, ResponseError):
            # Handle Redis failures gracefully
            pass

    def clear(self, key, participant_identifier):
        try:
            # Remove the direct entry
            cache_key = COUNTER_CACHE_KEY % key
            pipe = self._redis.pipeline()
            freq, _ = pipe.hget(cache_key, participant_identifier).hdel(cache_key, participant_identifier).execute()

            # Remove from the histogram
            freq_cache_key = COUNTER_FREQ_CACHE_KEY % key
            self._redis.hincrby(freq_cache_key, freq or 0, -1)
        except (ConnectionError, ResponseError):
            # Handle Redis failures gracefully
            pass

    def get(self, key):
        try:
            cache_key = COUNTER_CACHE_KEY % key
            return self._redis.hlen(cache_key)
        except (ConnectionError, ResponseError):
            # Handle Redis failures gracefully
            return 0

    def get_frequency(self, key, participant_identifier):
        try:
            cache_key = COUNTER_CACHE_KEY % key
            freq = self._redis.hget(cache_key, participant_identifier)
            return int(freq) if freq else 0
        except (ConnectionError, ResponseError):
            # Handle Redis failures gracefully
            return 0

    def get_frequencies(self, key):
        try:
            freq_cache_key = COUNTER_FREQ_CACHE_KEY % key
            # In some cases when there are concurrent updates going on, there can
            # briefly be a negative result for some frequency count. We discard these
            # as they shouldn't really affect the result, and they are about to become
            # zero anyway.
            return dict((int(k), int(v)) for (k, v) in self._redis.hgetall(freq_cache_key).items() if int(v) > 0)
        except (ConnectionError, ResponseError):
            # Handle Redis failures gracefully
            return dict()

    def reset(self, key):
        try:
            cache_key = COUNTER_CACHE_KEY % key
            self._redis.delete(cache_key)
            freq_cache_key = COUNTER_FREQ_CACHE_KEY % key
            self._redis.delete(freq_cache_key)
            return True
        except (ConnectionError, ResponseError):
            # Handle Redis failures gracefully
            return False

    def reset_pattern(self, pattern_key):
        #similar to above, but can pass pattern as arg instead
        try:
            cache_key = COUNTER_CACHE_KEY % pattern_key
            for key in self._redis.keys(cache_key):
                self._redis.delete(key)
            freq_cache_key = COUNTER_FREQ_CACHE_KEY % pattern_key
            for key in self._redis.keys(freq_cache_key):
                self._redis.delete(key)
            return True
        except (ConnectionError, ResponseError):
            # Handle Redis failures gracefully
            return False
     
    def reset_prefix(self, key_prefix):
        # Delete all data in redis for a given key prefix
        from experiments.utils import grouper
        
        try:
            for key_pattern in [COUNTER_CACHE_KEY, COUNTER_FREQ_CACHE_KEY]:
                match = "%s:*" % (key_pattern % key_prefix)
                key_iter = self._redis.scan_iter(match)

                # Delete keys in groups of 1000 to prevent problems with long
                # running experiments having many participants
                for keys in grouper(key_iter, 1000):
                    # The last group will be padded with None to reach the specified batch
                    # size, so these are filtered out here
                    self._redis.delete(*filter(None, keys))
        except (ConnectionError, ResponseError):
            # Handle Redis failures gracefully
            pass
