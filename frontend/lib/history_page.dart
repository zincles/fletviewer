import 'dart:async';

import 'package:flutter/material.dart';

import 'core_client.dart';
import 'eh_gallery_pages.dart';
import 'pixiv_pages.dart';

/// Cross-Provider browse history backed by the Core history registry.
class HistoryPage extends StatefulWidget {
  const HistoryPage({super.key, required this.client});

  final CoreClient client;

  @override
  State<HistoryPage> createState() => _HistoryPageState();
}

class _HistoryPageState extends State<HistoryPage> {
  List<HistoryEntry> _entries = const [];
  bool _loading = true;
  bool _clearing = false;
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
      final entries = await widget.client.history();
      if (!mounted) return;
      setState(() {
        _entries = entries;
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

  Future<void> _clear() async {
    if (_entries.isEmpty || _clearing) return;
    setState(() => _clearing = true);
    try {
      await widget.client.clearHistory();
      if (!mounted) return;
      setState(() {
        _entries = const [];
        _clearing = false;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _clearing = false;
        _error = '$error';
      });
    }
  }

  void _open(HistoryEntry entry) {
    if (entry.kind == 'eh_gallery') {
      final separator = entry.media.indexOf(':');
      if (separator <= 0) return;
      final gid = int.tryParse(entry.media.substring(0, separator));
      final token = entry.media.substring(separator + 1);
      if (gid == null || token.isEmpty) return;
      Navigator.of(context).push<void>(
        MaterialPageRoute(
          builder: (_) => EhGalleryPage(
            client: widget.client,
            profile: entry.profile,
            summary: EhGallerySummary(
              gallery: EhGalleryRef(gid: gid, token: token),
              pageUrl: '',
              title: entry.title,
              category: null,
              published: null,
              uploader: null,
              pageCount: null,
              rating: null,
              language: null,
              tags: const [],
              coverUrl: null,
              coverWidth: null,
              coverHeight: null,
            ),
          ),
        ),
      );
      return;
    }
    if (entry.kind == 'pixiv_illust') {
      Navigator.of(context).push<void>(
        MaterialPageRoute(
          builder: (_) => PixivIllustPage(
            client: widget.client,
            profile: entry.profile,
            illustId: entry.media,
          ),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(18, 18, 18, 8),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '浏览历史',
                      style: Theme.of(context).textTheme.headlineSmall
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      _entries.isEmpty
                          ? '打开画廊或作品详情后会记录在这里。'
                          : '共 ${_entries.length} 条 · 本地存储，属于当前设备。',
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ],
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
              if (_entries.isNotEmpty)
                IconButton(
                  tooltip: '清除历史',
                  onPressed: _clearing ? null : _clear,
                  icon: _clearing
                      ? const SizedBox.square(
                          dimension: 18,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.delete_outline),
                ),
            ],
          ),
        ),
        if (_error != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(18, 4, 18, 0),
            child: Row(
              children: [
                Icon(Icons.error_outline, color: colors.error, size: 18),
                const SizedBox(width: 8),
                Expanded(child: Text(_error!)),
              ],
            ),
          ),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _entries.isEmpty
              ? const Center(
                  child: Text('暂无浏览历史', style: TextStyle(fontSize: 16)),
                )
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(18, 10, 18, 100),
                  itemCount: _entries.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 8),
                  itemBuilder: (context, index) {
                    final entry = _entries[index];
                    return Card(
                      child: ListTile(
                        key: Key('history-entry-$index'),
                        leading: Icon(
                          entry.provider == 'eh'
                              ? Icons.collections_bookmark_outlined
                              : Icons.brush_outlined,
                          color: colors.primary,
                        ),
                        title: Text(
                          entry.title,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                        subtitle: Text(
                          '${entry.provider} · ${entry.viewedAt}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        trailing: const Icon(Icons.chevron_right),
                        onTap: () => _open(entry),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }
}
