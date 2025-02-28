# -*- coding: utf-8 -*-
import logging

from celery.task import task

from alarm_backends.core.alert import Alert
from alarm_backends.core.alert.alert import AlertKey
from alarm_backends.service.composite.processor import CompositeProcessor
from core.prometheus import metrics

logger = logging.getLogger("composite")


@task(ignore_result=True, queue="celery_composite")
def check_action_and_composite(alert_key: AlertKey, alert_status: str, composite_strategy_ids: list = None):
    """
    :param alert_key: 告警标识
    :param alert_status: 告警状态
    :param composite_strategy_ids: 待检测关联策略ID列表
    :return:
    """
    alert = Alert.get(alert_key)

    if not alert:
        logger.info("[composite] alert(%s) not found, skip it", alert_key)
        return

    if not alert.bk_biz_id:
        logger.info("[composite] alert(%s) bk_biz_id is empty, skip it", alert_key)
        return

    exc = None

    try:
        with metrics.COMPOSITE_PROCESS_TIME.labels(strategy_id=metrics.TOTAL_TAG).time():
            processor = CompositeProcessor(
                alert=alert, alert_status=alert_status, composite_strategy_ids=composite_strategy_ids
            )
            processor.process()
    except Exception as e:
        exc = e
        logger.exception("[composite] alert(%s) process error: %s", alert.id, e)

    metrics.COMPOSITE_PROCESS_COUNT.labels(
        strategy_id=metrics.TOTAL_TAG, status=metrics.StatusEnum.from_exc(exc), exception=exc
    ).inc()
    metrics.report_all()
