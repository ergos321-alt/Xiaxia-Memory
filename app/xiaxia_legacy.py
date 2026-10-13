"""Install the accepted fence before the existing Memory app serves requests."""
import os
from urllib.parse import urlparse
from flask import jsonify
from .auth import api_auth_required
from .xiaxia_cutover import WriteFence, install_legacy_fence


def install(app):
    fence = WriteFence(os.environ.get('XIAXIA_LEGACY_FENCE_DIR', '/tmp/xiaxia-legacy-cutover'))
    fence.freeze()
    app.config['XIAXIA_LEGACY_ALLOW_THAW'] = os.environ.get('XIAXIA_LEGACY_ALLOW_THAW', 'false').lower() == 'true'
    install_legacy_fence(app, fence)

    @app.get('/api/v1/cutover/status')
    @api_auth_required
    def status():
        with fence.try_lease() as acquired:
            with fence.connect() as conn:
                pending = conn.execute('SELECT count(*) FROM events WHERE after_state IS NULL').fetchone()[0]
            frozen = fence.is_frozen()
            engine = app.extensions['memory_engine']
            embedder = getattr(getattr(engine, 'mem0', None), 'embedding_model', None)
            client = getattr(embedder, 'client', None)
            configuration = getattr(embedder, 'config', None)
            return jsonify({
                'frozen': frozen, 'active_writers': 0 if acquired else 1,
                'pending_intents': pending, 'drained': frozen and acquired and not pending,
                'allow_thaw': app.config['XIAXIA_LEGACY_ALLOW_THAW'],
                'deployment_commit': os.environ.get('RENDER_GIT_COMMIT', ''),
                'instance_id': os.environ.get('RENDER_INSTANCE_ID', ''),
                'embedding': {
                    'provider': type(embedder).__name__ if embedder else 'UNKNOWN',
                    'endpoint_host': urlparse(str(getattr(client, 'base_url', app.config.get('QWEN_BASE_URL', '')))).hostname,
                    'model': getattr(configuration, 'model', app.config.get('QWEN_EMBEDDING_MODEL')),
                    'dimensions': getattr(configuration, 'embedding_dims', app.config.get('EMBEDDING_DIMENSIONS')),
                    'dimensions_parameter': getattr(embedder, '_pass_dimensions_to_api', None),
                    'newline_preprocessing': 'replace_newlines_with_spaces',
                    'immutable_model_revision': 'UNKNOWN',
                },
            })
    app.extensions['xiaxia_cutover_fence'] = fence
