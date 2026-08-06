import 'dart:async';

import 'package:flutter/material.dart';

import 'core_client.dart';

/// Runtime diagnostics: identity, storage, profiles and cache accounting.
class DebugPage extends StatefulWidget {
  const DebugPage({super.key, required this.client});

  final CoreClient client;

  @override
  State<DebugPage> createState() => _DebugPageState();
}

class _DebugPageState extends State<DebugPage> {
  CoreSnapshot? _runtime;
  List<ProfileSnapshot> _profiles = const [];
  ImageCacheSnapshot? _cache;
  List<OperationSnapshotView> _operations = const [];
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final results = await Future.wait<Object>([
        widget.client.runtime(),
        widget.client.profiles(),
        widget.client.imageCache(),
        widget.client.operations(),
      ]);
      if (!mounted) return;
      setState(() {
        _runtime = results[0] as CoreSnapshot;
        _profiles = results[1] as List<ProfileSnapshot>;
        _cache = results[2] as ImageCacheSnapshot;
        _operations = results[3] as List<OperationSnapshotView>;
        _loading = false;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '$error';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 100),
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                '调试',
                style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
            IconButton.filledTonal(
              tooltip: '刷新',
              onPressed: _loading ? null : _load,
              icon: _loading
                  ? const SizedBox.square(
                      dimension: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh),
            ),
          ],
        ),
        const SizedBox(height: 12),
        if (_error != null)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Text(_error!, style: const TextStyle(color: Colors.red)),
            ),
          ),
        if (_runtime case final runtime?)
          _DebugCard(
            title: 'Runtime',
            rows: [
              ('状态', runtime.state),
              ('Core 版本', runtime.coreVersion),
              ('API 协议', 'v${runtime.apiProtocolVersion}'),
              ('Runtime ID', runtime.runtimeId),
              ('实例', runtime.instanceName),
              ('运行时长', '${runtime.uptimeSeconds} 秒'),
              ('排队命令', '${runtime.queuedCommands}'),
              ('活跃操作', '${runtime.activeOperations}'),
              ('事件序列', '${runtime.latestEventSequence}'),
            ],
          ),
        if (_runtime case final runtime?)
          _DebugCard(
            title: '存储四域',
            rows: [
              ('Data', runtime.storage.dataIdentity),
              ('Cache', runtime.storage.cacheIdentity),
              ('Downloads', runtime.storage.downloadsIdentity),
              ('Temp', runtime.storage.tempIdentity),
              ('数据库字节', runtime.storage.databaseBytes.toString()),
            ],
          ),
        _DebugCard(
          title: 'Provider 会话',
          rows: [
            for (final profile in _profiles)
              (
                '${profile.provider}/${profile.profile}',
                'gen ${profile.generation} · Cookie: ${profile.hasCookie ? '已加载' : '未配置'} · API: ${profile.hasApiCredentials ? '已加载' : '未配置'}',
              ),
            if (_profiles.isEmpty) ('（无）', ''),
          ],
        ),
        if (_cache case final cache?)
          _DebugCard(
            title: '图片缓存',
            rows: [
              (
                '内存',
                '${_bytes(cache.memoryBytes)} / ${_bytes(cache.memoryLimitBytes)}（${cache.memoryEntries} 条）',
              ),
              (
                '在途',
                '${_bytes(cache.inflightBytes)} / ${_bytes(cache.inflightLimitBytes)}',
              ),
              ('磁盘', '${_bytes(cache.diskBytes)}（${cache.diskBlobCount} blob）'),
              ('别名', '${cache.aliasCount}'),
              ('资源/页', '${cache.resourceCount} / ${cache.pageCount}'),
              (
                '按 Provider',
                cache.byProvider.entries
                    .map((entry) => '${entry.key}: ${entry.value}')
                    .join(' · '),
              ),
            ],
          ),
        _DebugCard(
          title: '操作（活跃/保留）',
          rows: [
            for (final operation in _operations.take(12))
              (
                operation.kind,
                '${operation.state} · ${operation.phase} · ${operation.id}',
              ),
            if (_operations.isEmpty) ('（无）', ''),
          ],
        ),
      ],
    );
  }

  static String _bytes(int value) {
    if (value >= 1024 * 1024) {
      return '${(value / 1024 / 1024).toStringAsFixed(1)} MiB';
    }
    if (value >= 1024) {
      return '${(value / 1024).toStringAsFixed(1)} KiB';
    }
    return '$value B';
  }
}

class _DebugCard extends StatelessWidget {
  const _DebugCard({required this.title, required this.rows});

  final String title;
  final List<(String, String)> rows;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              title,
              style: Theme.of(
                context,
              ).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 8),
            for (final (label, value) in rows)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SizedBox(
                      width: 130,
                      child: Text(
                        label,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ),
                    Expanded(
                      child: SelectableText(
                        value,
                        style: const TextStyle(
                          fontFeatures: [FontFeature.tabularFigures()],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}
