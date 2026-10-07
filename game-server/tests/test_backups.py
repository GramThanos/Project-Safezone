"""Tests for the world backup archive.

A backup is only worth something if it can be opened outside this system - on
an operator's desktop, with whatever archiver they have - and if putting it back
gives the world its files as they were.

The first half pins the gzip header. `tarfile` names the compressed member
after the file it writes to, and the archive is written to a `.partial` name
before being moved into place, so it used to carry `<name>.tar.gz.partial` as
its inner name. 7-Zip opens the gzip layer, shows the tar under that name, and
then will not open it as a tar - the archive looked broken although every byte
of it was fine. The same goes for the tar's root: added as `.`, the whole world
sat inside one nameless folder that 7-Zip shows as an empty-looking entry, so
the contents are stored at the top level instead - and archives taken the old
way must still restore.

The second half pins what the tar keeps: permissions, modification times and
owner, which a zip would not carry and are the reason the format is tar.
"""
import gzip
import os
import stat
import sys
import tarfile
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    import pwd  # noqa: F401
except ImportError:
    sys.modules['pwd'] = types.ModuleType('pwd')

try:
    import config
    import backups
    IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - depends on the host
    config = None
    backups = None
    IMPORT_ERROR = e

SERVER = 'alpha'


def _gzip_member_name(path):
    """The original-file name a gzip header records, or None if it has none."""
    with open(path, 'rb') as f:
        header = f.read(10)
        if not header[3] & 0x08:  # FNAME
            return None
        if header[3] & 0x04:  # FEXTRA comes first
            f.read(int.from_bytes(f.read(2), 'little'))
        name = b''
        while (byte := f.read(1)) not in (b'', b'\0'):
            name += byte
    return name.decode('latin-1')


@unittest.skipIf(IMPORT_ERROR is not None, f'backups could not be imported: {IMPORT_ERROR}')
class BackupArchiveTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = os.path.join(self.tmp.name, 'Zomboid')
        self.backup_root = os.path.join(self.tmp.name, 'backups')
        for name, value in (('ZOMBOID_DATA_DIR', data), ('BACKUP_DIR', self.backup_root)):
            patcher = mock.patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.save = os.path.join(data, 'Saves', 'Multiplayer', SERVER)
        os.makedirs(os.path.join(self.save, 'map'))
        self.files = {
            'map_meta.bin': b'meta',
            os.path.join('map', '0_0.bin'): b'chunk',
        }
        for rel, body in self.files.items():
            with open(os.path.join(self.save, rel), 'wb') as f:
                f.write(body)
        self.mtime = 1700000000
        os.utime(os.path.join(self.save, 'map_meta.bin'), (self.mtime, self.mtime))

    def _create(self, note=None):
        name, error = backups.create(SERVER, note)
        self.assertIsNone(error)
        return name, os.path.join(self.backup_root, SERVER, name)

    def test_gzip_header_names_the_tar_not_the_partial_file(self):
        name, path = self._create('before mod update')
        self.assertEqual(_gzip_member_name(path), name[:-len('.gz')])

    def test_archive_is_a_readable_gzip_tar(self):
        _, path = self._create()
        with gzip.open(path, 'rb') as inner, tarfile.open(fileobj=inner, mode='r:') as tar:
            names = set(tar.getnames())
        for rel in self.files:
            self.assertIn(rel.replace(os.sep, '/'), names)

    def test_contents_sit_at_the_top_not_under_a_dot_folder(self):
        _, path = self._create()
        with tarfile.open(path, 'r:gz') as tar:
            names = tar.getnames()
        self.assertEqual([n for n in names if n == '.' or n.startswith('./')], [])
        self.assertIn('map', names)

    def test_no_partial_file_is_left_behind(self):
        self._create()
        leftovers = [n for n in os.listdir(os.path.join(self.backup_root, SERVER))
                     if n.endswith('.partial')]
        self.assertEqual(leftovers, [])

    def test_archive_keeps_mode_mtime_and_owner(self):
        _, path = self._create()
        source = os.stat(os.path.join(self.save, 'map_meta.bin'))
        with tarfile.open(path, 'r:gz') as tar:
            member = tar.getmember('map_meta.bin')
        self.assertEqual(member.mode, stat.S_IMODE(source.st_mode))
        self.assertEqual(int(member.mtime), self.mtime)
        self.assertEqual(member.uid, source.st_uid)
        self.assertEqual(member.gid, source.st_gid)

    def test_restore_puts_back_contents_and_mtime(self):
        name, _ = self._create()
        with open(os.path.join(self.save, 'map_meta.bin'), 'wb') as f:
            f.write(b'overwritten after the backup')

        kept_aside, error = backups.restore(SERVER, name)
        self.assertIsNone(error)
        self.assertTrue(os.path.isdir(kept_aside))
        for rel, body in self.files.items():
            with open(os.path.join(self.save, rel), 'rb') as f:
                self.assertEqual(f.read(), body)
        restored = os.stat(os.path.join(self.save, 'map_meta.bin'))
        self.assertEqual(int(restored.st_mtime), self.mtime)

    def test_restore_accepts_the_old_dot_rooted_layout(self):
        name = '20240102-153000-old.tar.gz'
        os.makedirs(os.path.join(self.backup_root, SERVER))
        with tarfile.open(os.path.join(self.backup_root, SERVER, name), 'w:gz') as tar:
            tar.add(self.save, arcname='.')
        with open(os.path.join(self.save, 'map_meta.bin'), 'wb') as f:
            f.write(b'overwritten after the backup')

        _, error = backups.restore(SERVER, name)
        self.assertIsNone(error)
        for rel, body in self.files.items():
            with open(os.path.join(self.save, rel), 'rb') as f:
                self.assertEqual(f.read(), body)


if __name__ == '__main__':
    unittest.main()
