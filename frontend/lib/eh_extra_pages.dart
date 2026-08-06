import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import 'core_client.dart';
import 'eh_gallery_pages.dart';
import 'pixiv_pages.dart' show AuthRequiredView;

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
    final bytes = _bytes;
    if (bytes != null) {
      return Image.memory(bytes, fit: BoxFit.cover, gaplessPlayback: true);
    }
    return ColoredBox(
      color: colors.surfaceContainerHighest,
      child: Icon(
        Icons.collections_bookmark_outlined,
        color: colors.onSurfaceVariant.withValues(alpha: 0.5),
      ),
    );
  }
}

/// EH saved searches (subscription-style bookmarks of queries).
class EhFavoriteSearchesPage extends StatefulWidget {
  const EhFavoriteSearchesPage({
    super.key,
    required this.client,
    required this.profile,
  });

  final CoreClient client;
  final String profile;

  @override
  State<EhFavoriteSearchesPage> createState() => _EhFavoriteSearchesPageState();
}

class _EhFavoriteSearchesPageState extends State<EhFavoriteSearchesPage> {
  List<FavoriteSearch> _searches = const [];
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
      final searches = await widget.client.favoriteSearches();
      if (!mounted) return;
      setState(() {
        _searches = searches
            .where((search) => search.provider == 'eh')
            .toList(growable: false);
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

  Future<void> _create() async {
    final nameController = TextEditingController();
    final queryController = TextEditingController();
    final created = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('新建收藏搜索'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: nameController,
              autofocus: true,
              decoration: const InputDecoration(labelText: '名称'),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: queryController,
              decoration: const InputDecoration(labelText: '搜索词'),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('保存'),
          ),
        ],
      ),
    );
    nameController.dispose();
    queryController.dispose();
    if (created != true) return;
    final name = nameController.text.trim();
    final query = queryController.text.trim();
    if (name.isEmpty || query.isEmpty) return;
    try {
      await widget.client.createFavoriteSearch(
        provider: 'eh',
        profile: widget.profile,
        name: name,
        query: query,
      );
      if (!mounted) return;
      await _load();
    } on Object catch (error) {
      if (!mounted) return;
      setState(() => _error = '$error');
    }
  }

  Future<void> _delete(FavoriteSearch search) async {
    try {
      await widget.client.deleteFavoriteSearch(search.id);
      if (!mounted) return;
      await _load();
    } on Object catch (error) {
      if (!mounted) return;
      setState(() => _error = '$error');
    }
  }

  void _run(FavoriteSearch search) {
    Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (_) => _SavedSearchResultsPage(
          client: widget.client,
          profile: widget.profile,
          query: search.query,
        ),
      ),
    );
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
                      'E-Hentai · 订阅',
                      style: Theme.of(context).textTheme.headlineSmall
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '收藏的搜索词；点击条目执行搜索。',
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
              IconButton(
                tooltip: '新建收藏搜索',
                onPressed: _create,
                icon: const Icon(Icons.add),
              ),
            ],
          ),
        ),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _error != null
              ? Center(child: Text(_error!))
              : _searches.isEmpty
              ? const Center(
                  child: Text(
                    '暂无收藏搜索；点击右上角 + 新建。',
                    style: TextStyle(fontSize: 16),
                  ),
                )
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(18, 10, 18, 100),
                  itemCount: _searches.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 8),
                  itemBuilder: (context, index) {
                    final search = _searches[index];
                    return Card(
                      child: ListTile(
                        key: Key('eh-saved-search-${search.id}'),
                        leading: const Icon(Icons.bookmark_outline),
                        title: Text(search.name),
                        subtitle: Text(
                          search.query,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            IconButton(
                              tooltip: '执行搜索',
                              icon: const Icon(Icons.search),
                              onPressed: () => _run(search),
                            ),
                            IconButton(
                              tooltip: '删除',
                              icon: const Icon(Icons.delete_outline),
                              onPressed: () => _delete(search),
                            ),
                          ],
                        ),
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }
}

class _SavedSearchResultsPage extends StatefulWidget {
  const _SavedSearchResultsPage({
    required this.client,
    required this.profile,
    required this.query,
  });

  final CoreClient client;
  final String profile;
  final String query;

  @override
  State<_SavedSearchResultsPage> createState() =>
      _SavedSearchResultsPageState();
}

class _SavedSearchResultsPageState extends State<_SavedSearchResultsPage> {
  EhHomePage? _page;
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
      final page = await widget.client.ehSearch(
        profile: widget.profile,
        search: widget.query,
      );
      if (!mounted) return;
      setState(() {
        _page = page;
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
    return Scaffold(
      appBar: AppBar(title: Text('搜索：${widget.query}')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
          ? Center(child: Text(_error!))
          : _page == null || _page!.galleries.isEmpty
          ? const Center(child: Text('没有结果'))
          : ListView.separated(
              padding: const EdgeInsets.fromLTRB(18, 14, 18, 40),
              itemCount: _page!.galleries.length,
              separatorBuilder: (_, _) => const SizedBox(height: 10),
              itemBuilder: (context, index) {
                final gallery = _page!.galleries[index];
                return ListTile(
                  key: Key('saved-result-${gallery.gallery.gid}'),
                  leading: const Icon(Icons.collections_bookmark_outlined),
                  title: Text(
                    gallery.title,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  subtitle: Text('#${gallery.gallery.gid}'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => Navigator.of(context).push<void>(
                    MaterialPageRoute(
                      builder: (_) => EhGalleryPage(
                        client: widget.client,
                        profile: widget.profile,
                        summary: gallery,
                      ),
                    ),
                  ),
                );
              },
            ),
    );
  }
}
