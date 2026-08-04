import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

import 'core_client.dart';
import 'src/rust/frb_generated.dart';

final class RuntimeLaunchException implements Exception {
  RuntimeLaunchException(this.message, [this.cause]);

  final String message;
  final Object? cause;

  @override
  String toString() => message;
}

final class RuntimeStoragePaths {
  const RuntimeStoragePaths({
    required this.data,
    required this.cache,
    required this.downloads,
    required this.temp,
  });

  final String data;
  final String cache;
  final String downloads;
  final String temp;

  Map<String, String> get domains => {
    'data': data,
    'cache': cache,
    'downloads': downloads,
    'temp': temp,
  };
}

final class RuntimeConnection {
  const RuntimeConnection({
    required this.client,
    required this.snapshot,
    required this.storage,
  });

  final CoreClient client;
  final CoreSnapshot snapshot;
  final RuntimeStoragePaths storage;
}

typedef RuntimePathResolver = Future<RuntimeStoragePaths> Function();
typedef NativeCoreStarter =
    Future<CoreClient> Function(RuntimeStoragePaths paths);
typedef BridgeInitializer = Future<void> Function();

Future<void>? _rustInitialization;

Future<void> initializeRustBridge() async {
  final existing = _rustInitialization;
  if (existing != null) {
    await existing;
    return;
  }
  final initialization = RustLib.init();
  _rustInitialization = initialization;
  try {
    await initialization;
  } on Object {
    if (identical(_rustInitialization, initialization)) {
      _rustInitialization = null;
    }
    rethrow;
  }
}

final class NativeRuntimeLauncher {
  NativeRuntimeLauncher({
    this.expectedInstanceName = 'fvcore',
    RuntimePathResolver? pathResolver,
    NativeCoreStarter? coreStarter,
    BridgeInitializer? bridgeInitializer,
  }) : _pathResolver = pathResolver ?? resolveRuntimeStoragePaths,
       _coreStarter = coreStarter ?? _startNativeCore,
       _bridgeInitializer = bridgeInitializer ?? initializeRustBridge;

  final String expectedInstanceName;
  final RuntimePathResolver _pathResolver;
  final NativeCoreStarter _coreStarter;
  final BridgeInitializer _bridgeInitializer;

  CoreClient? _client;
  RuntimeConnection? _connection;
  Future<RuntimeConnection>? _pending;
  bool _closeRequested = false;

  RuntimeConnection? get connection => _connection;

  Future<RuntimeConnection> connect() {
    final existing = _connection;
    if (existing != null) return Future.value(existing);
    final pending = _pending;
    if (pending != null) return pending;
    if (_closeRequested) {
      return Future.error(RuntimeLaunchException('本地 fvcore Runtime 已关闭'));
    }
    final future = _connectOnce();
    _pending = future;
    return future;
  }

  Future<RuntimeConnection> _connectOnce() async {
    CoreClient? started;
    try {
      await _bridgeInitializer();
      final storage = await _pathResolver();
      started = await _coreStarter(storage);
      final snapshot = await started.runtime();
      _validateSnapshot(snapshot, storage);
      if (_closeRequested) {
        throw RuntimeLaunchException('本地 fvcore Runtime 启动已取消');
      }
      final connection = RuntimeConnection(
        client: started,
        snapshot: snapshot,
        storage: storage,
      );
      _client = started;
      _connection = connection;
      return connection;
    } on RuntimeLaunchException {
      if (started != null) await _closeQuietly(started);
      rethrow;
    } on CoreApiException catch (error) {
      if (started != null) await _closeQuietly(started);
      throw RuntimeLaunchException(_startupMessage(error), error);
    } on Object catch (error) {
      if (started != null) await _closeQuietly(started);
      throw RuntimeLaunchException('无法启动本地 fvcore Runtime', error);
    } finally {
      _pending = null;
    }
  }

  void _validateSnapshot(CoreSnapshot snapshot, RuntimeStoragePaths storage) {
    if (snapshot.apiProtocolVersion != supportedApiProtocolVersion) {
      throw RuntimeLaunchException(
        'fvcore API 协议不兼容：期望 $supportedApiProtocolVersion，实际 ${snapshot.apiProtocolVersion}',
      );
    }
    if (snapshot.runtimeId.isEmpty || snapshot.coreVersion.isEmpty) {
      throw RuntimeLaunchException('fvcore Runtime identity 不完整');
    }
    if (snapshot.instanceName != expectedInstanceName) {
      throw RuntimeLaunchException('fvcore instance identity 不匹配');
    }
    if (snapshot.state != 'ready') {
      throw RuntimeLaunchException('fvcore Runtime 未进入 ready 状态');
    }
    for (final entry in storage.domains.entries) {
      final expected = storageIdentity(entry.key, entry.value);
      if (snapshot.storage.identityFor(entry.key) != expected) {
        throw RuntimeLaunchException(
          'fvcore ${entry.key} storage identity 不匹配',
        );
      }
    }
  }

  Future<void> close() async {
    _closeRequested = true;
    final pending = _pending;
    if (pending != null) {
      try {
        await pending;
      } on Object {
        // Startup owns cleanup of a partially-created Runtime.
      }
    }
    _connection = null;
    final client = _client;
    _client = null;
    if (client != null) await client.close();
  }
}

Future<RuntimeStoragePaths> resolveRuntimeStoragePaths() async {
  final support = await getApplicationSupportDirectory();
  final cache = await getApplicationCacheDirectory();
  final temporary = await getTemporaryDirectory();
  return RuntimeStoragePaths(
    data: _join(support.path, 'fvcore', 'Data'),
    cache: _join(cache.path, 'fvcore', 'Cache'),
    downloads: _join(support.path, 'fvcore', 'Downloads'),
    temp: _join(temporary.path, 'fvcore', 'Temp'),
  );
}

Future<CoreClient> _startNativeCore(RuntimeStoragePaths paths) {
  return NativeCoreClient.start(
    dataDir: paths.data,
    cacheDir: paths.cache,
    downloadsDir: paths.downloads,
    tempDir: paths.temp,
  );
}

Future<void> _closeQuietly(CoreClient client) async {
  try {
    await client.close();
  } on Object {
    // Preserve the startup error that triggered cleanup.
  }
}

String _startupMessage(CoreApiException error) => switch (error.code) {
  'already_running' => '本地存储已由另一个 fvcore Runtime 占用',
  'invalid_config' => '本地 fvcore Runtime 配置无效',
  'io' => '本地 fvcore Runtime 无法访问应用存储',
  _ => '本地 fvcore Runtime 启动失败（${error.code}）',
};

const _storageDomains = {'data', 'cache', 'downloads', 'temp'};

String storageIdentity(String domain, String path) {
  if (!_storageDomains.contains(domain)) {
    throw ArgumentError.value(domain, 'domain', 'unknown storage domain');
  }
  final canonical = _canonicalStoragePath(path);
  final input = utf8.encode('fvcore-storage-v1:$domain:$canonical');
  var hash = 0xcbf29ce484222325;
  for (final byte in input) {
    hash ^= byte;
    hash = (hash * 0x100000001b3) & 0xffffffffffffffff;
  }
  final high = (hash >> 32) & 0xffffffff;
  final low = hash & 0xffffffff;
  return 'v1-${high.toRadixString(16).padLeft(8, '0')}${low.toRadixString(16).padLeft(8, '0')}';
}

String _canonicalStoragePath(String path) {
  final directory = Directory(path);
  if (directory.existsSync()) {
    try {
      return directory.resolveSymbolicLinksSync();
    } on FileSystemException {
      // Rust uses the same absolute fallback when canonicalization fails.
    }
  }
  return directory.absolute.path;
}

String _join(String first, String second, [String? third]) {
  return [
    first,
    second,
    third,
  ].whereType<String>().join(Platform.pathSeparator);
}
