# Copyright (C) 2019 Kataiser & https://github.com/Kataiser/tf2-rich-presence/contributors
# https://github.com/Kataiser/tf2-rich-presence/blob/master/LICENSE

import getpass
import gzip
import inspect
import os
import socket
import sys
import time
import traceback
import zlib
from operator import itemgetter
from typing import BinaryIO, List, Union

import sentry_sdk

import settings


# TODO: replace this whole thing with a real logger
class Log:
    def __init__(self, path=None):
        # find user's pc and account name
        user_identifier = getpass.getuser()
        user_pc_name = socket.gethostname()

        if path:
            self.filename = path
        else:
            days_since_epoch_local = int((time.time() + time.localtime().tm_gmtoff) / 86400)  # 86400 seconds in a day
            self.filename: Union[bytes, str] = os.path.join('logs', f'{user_pc_name}_{user_identifier}_{"{tf2rpvnum}"}_{generate_hash()}_{days_since_epoch_local}.log')

        # setup
        self.last_log_time = None
        self.console_log_path: Union[str, None] = None
        self.to_stderr: bool = False
        self.sentry_level: str = settings.get('sentry_level')
        self.enabled: bool = settings.get('log_level') != 'Off'
        self.log_levels: list = ['Debug', 'Info', 'Error', 'Critical', 'Off']
        self.log_level: str = settings.get('log_level')

        # set the user in Sentry, since log filename is no longer sent
        with sentry_sdk.configure_scope() as scope:
            scope.user = {'username': f'{user_pc_name}_{user_identifier}'}

        if self.enabled:
            if not os.path.isdir('logs'):
                os.mkdir('logs')

            self.log_levels_allowed = [level for level in self.log_levels if self.log_levels.index(level) >= self.log_levels.index(self.log_level)]
            self.log_file = open(self.filename, 'a', encoding='utf-8')
        else:
            self.log_levels_allowed = self.log_levels

        for old_filename in os.listdir('logs'):
            old_filename = os.path.join('logs', old_filename)

            if old_filename != self.filename and 'gzip' not in old_filename:
                if self.enabled:
                    self.log_file.close()
                    self.log_file = open(self.filename, 'a', encoding='utf-8')

        if not os.access('DB.json', os.W_OK) and not os.access(os.path.join('resources', 'DB.json'), os.W_OK):
            self.error("DB.json can't be written to. This could cause crashes")

    def __repr__(self):
        return f"logger.Log at {self.filename} (enabled={self.enabled} level={self.log_level}, stderr={self.to_stderr})"

    def __del__(self):
        if not self.log_file.closed:
            self.debug("Closing log file via destructor")
            self.log_file.close()

    # adds a line to the current log file
    def write_log(self, level: str, message_out: str):
        if self.enabled:
            current_time = time.perf_counter()

            if self.last_log_time:
                time_since_last: str = format(current_time - self.last_log_time, '.4f')  # the format() adds trailing zeroes
            else:
                time_since_last: str = '0.0000'

            full_line: str = f"[{int(time.time())} +{time_since_last}] {level}: {message_out}\n"

            # log breadcrumb to Sentry
            sentry_sdk.add_breadcrumb(message=full_line, level=level.lower().replace('critical', 'fatal'))

            try:
                self.log_file.write(full_line)
                self.log_file.flush()
            except UnicodeEncodeError as error:
                self.error(f"Couldn't write log due to UnicodeEncodeError: {error}")

            if self.to_stderr:
                print(full_line.rstrip('\n'), file=sys.stderr)

            self.last_log_time = current_time

    # a log with a level of INFO (not commonly used)
    def info(self, message_in):
        if 'Info' in self.log_levels_allowed:
            self.write_log('INFO', message_in)

    # a log with a level of DEBUG (most things)
    def debug(self, message_in):
        if 'Debug' in self.log_levels_allowed:
            self.write_log('DEBUG', message_in)

    # a log with a level of ERROR (caught, non-fatal errors)
    def error(self, message_in):
        if 'Error' in self.log_levels_allowed:
            self.write_log('ERROR', f"[{get_caller_filename()}] {message_in}")

        if self.sentry_level == 'All errors':
            sentry_sdk.capture_message(f"Reporting non-critical ERROR: {message_in}")

    # a log with a level of CRITICAL (uncaught, fatal errors, probably sent to Sentry)
    def critical(self, message_in):
        # TODO: append source hash to message (for errors too)

        if 'Critical' in self.log_levels_allowed:
            self.write_log('CRITICAL', message_in)

    # deletes older log files and compresses the ones the rest
    def cleanup(self, max_logs: int):
        all_logs = [os.path.join('logs', log) for log in os.listdir('logs')]
        all_logs_times = [(log_filename, os.stat(log_filename).st_mtime_ns) for log_filename in all_logs]
        all_logs_sorted = [log_pair[0] for log_pair in sorted(all_logs_times, key=itemgetter(1))]
        overshoot: int = max_logs - len(all_logs_sorted)
        deleted = []
        compressed = []

        while overshoot < 0:
            log_to_delete: str = all_logs_sorted.pop(0)
            deleted.append(log_to_delete)

            try:
                os.remove(log_to_delete)
            except Exception:
                self.error(f"Couldn't delete log file {log_to_delete}: {traceback.format_exc()}")

            overshoot = max_logs - len(all_logs_sorted)

        self.debug(f"Deleted {len(deleted)} log(s): {deleted}")

        for old_log in [log for log in all_logs if not log.endswith('.gz') and os.path.exists(log) and log != self.filename]:
            with open(old_log, 'rb') as old_log_r:
                data_in = old_log_r.read()
                data_out = gzip.compress(data_in)

                with open(f'{old_log}.gz', 'wb') as old_log_w:
                    old_log_w.write(data_out)

            os.remove(old_log)
            comp_ratio = round(len(data_out) / len(data_in), 3) if data_in else None  # fixes a ZeroDivisionError
            compressed.append((old_log, comp_ratio))

        self.debug(f"Compressed {len(compressed)} log(s): {compressed}")


# generates a short hash string from several source files
def generate_hash() -> str:
    # TODO: cached per working dir, if possible

    files_to_hash: List[str] = ['main.py', 'console_log.py', 'configs.py', 'custom_maps.py', 'logger.py', 'updater.py', 'launcher.py', 'settings.py', 'detect_system_language.py',
                                'maps.json', 'localization.json', 'APIs']
    files_to_hash_data: List = []
    build_folder = [item for item in os.listdir('.') if item.startswith('TF2 Rich Presence v') and os.path.isdir(item)]

    for file_to_hash in files_to_hash:
        if build_folder:
            file_to_hash = f'{build_folder[0]}\\resources\\{file_to_hash}'

        try:
            file: BinaryIO = open(os.path.join('resources', file_to_hash), 'rb')
        except FileNotFoundError:
            file: BinaryIO = open(file_to_hash, 'rb')

        file_read = file.read()

        if 'launcher' in file_to_hash:
            file_read = file_read.replace(b'{tf2rpvnum}-dev', b'{tf2rpvnum}')

        files_to_hash_data.append(file_read)
        file.close()

    hash_int = zlib.adler32(b'\n'.join(files_to_hash_data))
    hash_hex = hex(hash_int)[2:10].ljust(8, '0')
    return hash_hex


def get_caller_filename() -> str:
    frame = inspect.stack()[2]
    module = inspect.getmodule(frame[0])
    caller_filename = os.path.basename(module.__file__)
    return caller_filename


if __name__ == '__main__':
    log = Log()
    # log.debug(f"Current log: {log.filename}")
