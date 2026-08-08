import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import 'core_client.dart';
import 'core_image_view.dart';
import 'eh_gallery_pages.dart';
import 'pixiv_pages.dart' show AuthRequiredView;

/// EH gallery toplist with rank badges.
class EhToplistView extends StatefulWidget {
  const EhToplistView({super.key, required this.client, required this.profile});

  final CoreClient client;
  final String profile;

  @override
  State<EhToplistView> createState() => _EhToplistViewState();
}

class _EhToplistViewState extends State<EhToplistView> {
  static const _periods = <(String, int)>[
    ('全部', 11),
    ('年度', 12),
    ('月度', 13),
    ('昨日', 15),
  ];
  List<EhToplistItem> _items = const [];
  int _tl = 11;
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
      final page = await widget.client.ehToplist(
        profile: widget.profile,
        tl: _tl,
      );
      if (!mounted) return;
      setState(() {
        _items = page.items;
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
                      'E-Hentai · 排行榜',
                      style: Theme.of(context).textTheme.headlineSmall
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'EH 官方 toplist（当前周期榜单）。',
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
            ],
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(18, 0, 18, 4),
          child: Align(
            alignment: Alignment.centerLeft,
            child: SegmentedButton<int>(
              segments: [
                for (final (label, value) in _EhToplistViewState._periods)
                  ButtonSegment(value: value, label: Text(label)),
              ],
              selected: {_tl},
              onSelectionChanged: (selection) {
                setState(() => _tl = selection.first);
                unawaited(_load());
              },
            ),
          ),
        ),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
              ? Center(child: Text(_error!))
              : _items.isEmpty
              ? const Center(
                  child: Text('排行榜为空', style: TextStyle(fontSize: 16)),
                )
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(18, 10, 18, 100),
                  itemCount: _items.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 10),
                  itemBuilder: (context, index) => _ToplistTile(
                    client: widget.client,
                    profile: widget.profile,
                    item: _items[index],
                    fallbackRank: index + 1,
                  ),
                ),
        ),
      ],
    );
  }
}

class _ToplistTile extends StatelessWidget {
  const _ToplistTile({
    required this.client,
    required this.profile,
    required this.item,
    required this.fallbackRank,
  });

  final CoreClient client;
  final String profile;
  final EhToplistItem item;
  final int fallbackRank;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: ListTile(
        key: Key('eh-toplist-${item.gallery.gid}'),
        leading: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 40,
              child: Text(
                '#${item.rank ?? fallbackRank}',
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontWeight: FontWeight.w800,
                  color: colors.primary,
                ),
              ),
            ),
            const SizedBox(width: 6),
            SizedBox(
              width: 56,
              height: 72,
              child: _FavoriteCover(
                client: client,
                profile: profile,
                gallery: item.gallery,
                thumbnailUrl: item.thumbnailUrl,
              ),
            ),
          ],
        ),
        title: Text(item.title, maxLines: 2, overflow: TextOverflow.ellipsis),
        subtitle: Text('#${item.gallery.gid}'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => Navigator.of(context).push<void>(
          MaterialPageRoute(
            builder: (_) => EhGalleryPage(
              client: client,
              profile: profile,
              summary: EhGallerySummary(
                gallery: item.gallery,
                pageUrl: '',
                title: item.title,
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
        ),
      ),
    );
  }
}

/// Authenticated EH favorites listing with signed-out guidance.
class EhFavoritesView extends StatefulWidget {
  const EhFavoritesView({
    super.key,
    required this.client,
    required this.profile,
  });

  final CoreClient client;
  final String profile;

  @override
  State<EhFavoritesView> createState() => _EhFavoritesPageState();
}

class _EhFavoritesPageState extends State<EhFavoritesView> {
  List<EhFavoriteItem> _items = const [];
  bool _loading = true;
  bool _authRequired = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _authRequired = false;
      _error = null;
    });
    try {
      final page = await widget.client.ehFavorites(profile: widget.profile);
      if (!mounted) return;
      setState(() {
        _items = page.items;
        _loading = false;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        if (error is CoreApiException &&
            error.code == 'authentication_required') {
          _authRequired = true;
        } else {
          _error = '$error';
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_authRequired) {
      return const AuthRequiredView(providerLabel: 'E-Hentai');
    }
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
                      'E-Hentai · 收藏',
                      style: Theme.of(context).textTheme.headlineSmall
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '通过 fvcore Provider session 读取真实收藏列表。',
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
            ],
          ),
        ),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
              ? Center(child: Text(_error!))
              : _items.isEmpty
              ? const Center(
                  child: Text('暂无收藏', style: TextStyle(fontSize: 16)),
                )
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(18, 10, 18, 100),
                  itemCount: _items.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 10),
                  itemBuilder: (context, index) => _FavoriteTile(
                    client: widget.client,
                    profile: widget.profile,
                    item: _items[index],
                  ),
                ),
        ),
      ],
    );
  }
}

class _FavoriteTile extends StatelessWidget {
  const _FavoriteTile({
    required this.client,
    required this.profile,
    required this.item,
  });

  final CoreClient client;
  final String profile;
  final EhFavoriteItem item;

  @override
  Widget build(BuildContext context) {
    return Card(
      clipBehavior: Clip.antiAlias,
      child: ListTile(
        key: Key('eh-favorite-${item.gallery.gid}'),
        leading: SizedBox(
          width: 56,
          height: 72,
          child: _FavoriteCover(
            client: client,
            profile: profile,
            gallery: item.gallery,
            thumbnailUrl: item.thumbnailUrl,
          ),
        ),
        title: Text(item.title, maxLines: 2, overflow: TextOverflow.ellipsis),
        subtitle: Text('#${item.gallery.gid}'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => Navigator.of(context).push<void>(
          MaterialPageRoute(
            builder: (_) => EhGalleryPage(
              client: client,
              profile: profile,
              summary: EhGallerySummary(
                gallery: item.gallery,
                pageUrl: '',
                title: item.title,
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
        ),
      ),
    );
  }
}

class _FavoriteCover extends StatefulWidget {
  const _FavoriteCover({
    required this.client,
    required this.profile,
    required this.gallery,
    this.thumbnailUrl,
  });

  final CoreClient client;
  final String profile;
  final EhGalleryRef gallery;
  final String? thumbnailUrl;

  @override
  State<_FavoriteCover> createState() => _FavoriteCoverState();
}

class _FavoriteCoverState extends State<_FavoriteCover> {
  Uint8List? _bytes;
  int _requestRevision = 0;

  @override
  void initState() {
    super.initState();
    if (widget.thumbnailUrl != null) {
      unawaited(_load());
    }
  }

  @override
  void dispose() {
    _requestRevision++;
    super.dispose();
  }

  Future<void> _load() async {
    final revision = ++_requestRevision;
    try {
      var operation = await widget.client.startEhThumbnailFetch(
        profile: widget.profile,
        gallery: widget.gallery,
        page: 0,
        imageUrl: widget.thumbnailUrl!,
      );
      if (!_isCurrent(revision)) return;
      while (!operation.state.isTerminal) {
        await Future<void>.delayed(const Duration(milliseconds: 200));
        if (!_isCurrent(revision)) return;
        operation = await widget.client.operation(operation.id);
        if (!_isCurrent(revision)) return;
      }
      if (operation.state != CoreOperationState.completed) return;
      final resource = operation.resource;
      if (resource == null) return;
      final bytes = await widget.client.imageResource(
        resource.contentMd5,
        resource.extension,
      );
      if (bytes.length != resource.byteLength) return;
      if (!_isCurrent(revision)) return;
      setState(() => _bytes = bytes);
    } on Object {
      // 封面失败保留占位。
    }
  }

  bool _isCurrent(int revision) => mounted && revision == _requestRevision;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return FadeInImageBox(
      bytes: _bytes,
      placeholder: Icon(
        Icons.collections_bookmark_outlined,
        color: colors.onSurfaceVariant.withValues(alpha: 0.5),
      ),
    );
  }
}
