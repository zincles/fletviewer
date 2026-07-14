import 'package:flet/flet.dart';
import 'package:flutter/widgets.dart';

import 'fletviewer_native.dart';

class Extension extends FletExtension {
  @override
  Widget? createWidget(Key? key, Control control) {
    switch (control.type) {
      case "FletviewerImageReader":
        return FletviewerImageReaderControl(key: key, control: control);
      default:
        return null;
    }
  }
}
