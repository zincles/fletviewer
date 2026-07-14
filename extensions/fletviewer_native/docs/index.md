# Introduction

FletviewerNative for Flet.

## Examples

```
import flet as ft

from fletviewer_native import FletviewerNative


def main(page: ft.Page):
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

    page.add(

                ft.Container(height=150, width=300, alignment = ft.Alignment.CENTER, bgcolor=ft.Colors.PURPLE_200, content=FletviewerNative(
                    tooltip="My new FletviewerNative Control tooltip",
                    value = "My new FletviewerNative Flet Control",
                ),),

    )


ft.run(main)
```

## Classes

[FletviewerNative](FletviewerNative.md)
