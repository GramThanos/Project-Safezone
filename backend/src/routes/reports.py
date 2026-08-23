"""Player reports and ban appeals.

The one place in the product where somebody who is not staff can start a
conversation.

Appeals are deliberately reachable by a **banned** account. An appeal process a
banned person cannot reach is not an appeal process, so the middleware exempts
these endpoints from the ban refusal - and this module then restricts a banned
caller to appeals only, so the exemption cannot be used to file reports about
other people from behind a ban.
"""
import logging

from flask import Blueprint, request, jsonify, current_app

from src.database import db
from src.models.report import Report
from src.models.user import User
from src.middleware.auth import token_required
from src.utils import paging, alerting

logger = logging.getLogger(__name__)
reports_bp = Blueprint('reports', __name__, url_prefix='/api/reports')

MAX_BODY = 4000
# One open item at a time per person. Somebody with a genuine problem files one
# report; somebody filing five is either confused or abusing the queue, and
# either way the moderators should see the first one first.
MAX_OPEN_PER_USER = 3


@reports_bp.route('', methods=['GET'])
@token_required
def list_mine(current_user):
    """The caller's own reports and appeals, newest first."""
    try:
        limit, offset = paging.params(default_limit=25)
        with db.get_db() as session:
            query = (session.query(Report)
                     .filter_by(reporter_user_id=current_user['user_id'])
                     .order_by(Report.created_at.desc()))
            rows, total = paging.page(query, limit, offset)
            return jsonify({
                'reports': [r.to_dict() for r in rows],
                'pagination': paging.meta(total, limit, offset)
            }), 200
    except Exception as e:
        logger.error(f"List reports error: {e}")
        return jsonify({'error': 'Internal server error'}), 500


@reports_bp.route('', methods=['POST'])
def create_report():
    """File a report about another player, or appeal a ban."""
    @token_required
    def _create(current_user):
        data = request.get_json() or {}
        kind = (data.get('kind') or Report.KIND_REPORT).strip()
        body = (data.get('body') or '').strip()

        if kind not in Report.KINDS:
            return jsonify({'error': 'kind must be report or appeal'}), 400
        if not body:
            return jsonify({'error': 'Tell us what happened'}), 400
        if len(body) > MAX_BODY:
            return jsonify({'error': f'Keep it under {MAX_BODY} characters'}), 400

        # A banned account reaches this endpoint only to appeal. Without this the
        # ban exemption would become a way to keep reporting other people.
        if current_user['role'] == User.ROLE_BANNED and kind != Report.KIND_APPEAL:
            return jsonify({'error': 'A banned account can only file an appeal'}), 403

        try:
            with db.get_db() as session:
                open_count = (session.query(Report)
                              .filter_by(reporter_user_id=current_user['user_id'],
                                         status=Report.STATUS_OPEN)
                              .count())
                if open_count >= MAX_OPEN_PER_USER:
                    return jsonify({
                        'error': f'You already have {open_count} open items. '
                                 f'Wait for those to be answered first.'
                    }), 409

                report = Report(
                    kind=kind,
                    reporter_user_id=current_user['user_id'],
                    subject_username=(data.get('subject_username') or '').strip() or None,
                    server_id=data.get('server_id'),
                    body=body,
                )
                session.add(report)
                session.flush()

                label = 'appeal' if kind == Report.KIND_APPEAL else 'report'
                subject = report.subject_username
                server_id = report.server_id
                result = report.to_dict()

            # Announced once the row is really committed. The staff notification
            # used to be written inside the transaction and rolled back with it;
            # an alert is delivered by other means and cannot be taken back, so
            # it waits until there is something to be told about.
            #
            # Which staff, and where, is the channel configuration's problem
            # now - the staff inbox is subscribed to this by default, so the
            # notification that used to be written here still arrives.
            #
            # `detail` carries the opening lines to the inbox and to ops mail
            # and stops there: the text of a report is somebody accusing
            # somebody else, and a Discord channel usually has a wider
            # membership than the staff table does.
            alerting.emit('report.created',
                          f'New {label} from {current_user["username"]}',
                          detail=body[:200],
                          server_id=server_id,
                          link='/admin/reports',
                          fields=[('Kind', label),
                                  ('From', current_user['username']),
                                  ('About', subject)])

            return jsonify({
                'message': 'Submitted. Staff will look at it.',
                'report': result
            }), 201
        except Exception as e:
            logger.error(f"Create report error: {e}")
            return jsonify({'error': 'Internal server error'}), 500

    return _create()
