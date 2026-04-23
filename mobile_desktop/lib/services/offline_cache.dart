import 'package:sqflite/sqflite.dart';
import 'package:path_provider/path_provider.dart';

/// Persists offline Yjs updates per room so edits made without network
/// are replayed to the backend once the WebSocket reconnects.
class OfflineCache {
  OfflineCache._();
  static final OfflineCache instance = OfflineCache._();
  Database? _db;

  Future<Database> _open() async {
    if (_db != null) return _db!;
    final dir = await getApplicationDocumentsDirectory();
    final path = '${dir.path}/pilot_offline.db';
    _db = await openDatabase(path, version: 1, onCreate: (db, _) async {
      await db.execute('''
        CREATE TABLE updates (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          room TEXT NOT NULL,
          update_b64 TEXT NOT NULL,
          ts INTEGER NOT NULL,
          flushed INTEGER NOT NULL DEFAULT 0
        )
      ''');
    });
    return _db!;
  }

  Future<void> save(String room, String updateB64) async {
    final db = await _open();
    await db.insert('updates', {
      'room': room,
      'update_b64': updateB64,
      'ts': DateTime.now().millisecondsSinceEpoch,
      'flushed': 0,
    });
  }

  Future<List<Map<String, dynamic>>> pending(String room) async {
    final db = await _open();
    return db.query('updates', where: 'room = ? AND flushed = 0', whereArgs: [room]);
  }

  Future<void> markFlushed(List<int> ids) async {
    final db = await _open();
    final batch = db.batch();
    for (final id in ids) {
      batch.update('updates', {'flushed': 1}, where: 'id = ?', whereArgs: [id]);
    }
    await batch.commit(noResult: true);
  }
}
