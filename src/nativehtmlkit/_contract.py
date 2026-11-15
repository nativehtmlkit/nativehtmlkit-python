"""Names from the pinned Core wire-v1 contract (generated from contracts/core-v1-method-matrix.json).

Used to allow-list identifiers that diagnostics may record: anything else is replaced by a
fixed placeholder. tests/test_final_review.py checks this file against the snapshot.
"""
SOURCE_SHA256 = '236aeb6deb7188bd8bd272a2e7db202336dfcb85fa4048711a73f443fd2a01a5'

METHODS = frozenset((
    'app.activate', 'app.activated', 'app.before_quit', 'app.force_quit', 'app.ready', 'app.request_quit',
    'app.shutdown', 'bitmap.close', 'bitmap.create', 'bitmap.present', 'clipboard.read_text',
    'clipboard.write_text', 'desktop.open_external', 'desktop.paths', 'desktop.preferences',
    'desktop.preferences_changed', 'desktop.reveal_file', 'dialog.choose_folder', 'dialog.open_files',
    'dialog.save_file', 'document.command', 'document.error', 'document.event', 'document.get',
    'document.load', 'document.unload', 'host.capabilities', 'host.diagnostics', 'host.hello',
    'probe.get_text', 'probe.set_text', 'request.cancel', 'request.cancelled', 'window.before_close',
    'window.create', 'window.event', 'window.get', 'window.list', 'window.request_attention',
    'window.request_close', 'window.set',
))

DOCUMENT_OPS = frozenset((
    'add_class', 'add_stylesheet', 'append_text', 'batch', 'blur', 'check_validity', 'clear_selection',
    'close_dialog', 'copy_selection', 'css_profile', 'edit_command', 'element_at_point', 'explain', 'focus',
    'get_accessibility_tree', 'get_attribute', 'get_attributes', 'get_checked', 'get_computed_style',
    'get_control_selection', 'get_diagnostics', 'get_dialog', 'get_environment', 'get_files',
    'get_focused_element', 'get_form_data', 'get_html', 'get_node', 'get_options', 'get_pointer_capture',
    'get_popover', 'get_rect', 'get_resource_stats', 'get_scroll', 'get_selection', 'get_text',
    'get_validity', 'get_value', 'has_element', 'hide_popover', 'insert_html', 'list_stylesheets',
    'move_element', 'node_batch', 'node_children', 'node_of', 'purge_unused_resources', 'query',
    'query_nodes', 'register_resource_bundle', 'remove_attribute', 'remove_class', 'remove_element',
    'remove_stylesheet', 'replace_children_html', 'replace_control_range', 'replace_stylesheet',
    'request_submit', 'reset_form', 'scroll_by', 'scroll_into_view', 'scroll_to', 'select_text',
    'set_attribute', 'set_checked', 'set_control_selection', 'set_custom_validity', 'set_default_action',
    'set_environment', 'set_pointer_capture', 'set_scroll_follow', 'set_selected_values', 'set_text',
    'set_value', 'show_dialog', 'show_popover', 'text_at_point', 'text_rects', 'toggle_popover',
    'trim_children', 'unregister_resource_bundle',
))
