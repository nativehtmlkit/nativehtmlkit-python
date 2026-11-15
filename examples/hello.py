from nativehtmlkit import Application


def main():
    with Application.start(name='NativeHTMLKit Python Hello') as app:
        w = app.open_html('<main style="padding:20px"><h1>Python SDK</h1><button id="btn">Click</button><p id="status">Ready</p></main>')
        w.document.on('click', lambda _: w.document.set_text('status','Clicked'), element='btn')
        app.run()


if __name__ == '__main__':
    main()
