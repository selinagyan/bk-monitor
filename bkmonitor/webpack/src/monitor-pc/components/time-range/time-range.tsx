/*
 * Tencent is pleased to support the open source community by making
 * 蓝鲸智云PaaS平台 (BlueKing PaaS) available.
 *
 * Copyright (C) 2021 THL A29 Limited, a Tencent company.  All rights reserved.
 *
 * 蓝鲸智云PaaS平台 (BlueKing PaaS) is licensed under the MIT License.
 *
 * License for 蓝鲸智云PaaS平台 (BlueKing PaaS):
 *
 * ---------------------------------------------------
 * Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
 * documentation files (the "Software"), to deal in the Software without restriction, including without limitation
 * the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and
 * to permit persons to whom the Software is furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all copies or substantial portions of
 * the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
 * THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
 * CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
 * IN THE SOFTWARE.
 */
import { Component, Emit, Prop, Watch } from 'vue-property-decorator';
import { Component as tsc, modifiers } from 'vue-tsx-support';
import moment from 'moment';

import {
  DEFAULT_TIME_RANGE,
  handleTransformTime,
  handleTransformToTimestamp,
  intTimestampStr,
  shortcuts
} from './utils';

import './time-range.scss';

export type TimeRangeType = [string, string];

type TimeRangeDisplayType = 'normal' | 'simple' | 'border' | 'input';
interface IProps {
  value: TimeRangeType;
  type?: TimeRangeDisplayType;
  placement?: String;
}
interface IEvents {
  onChange: TimeRangeType;
}

@Component
export default class TimeRange extends tsc<IProps, IEvents> {
  @Prop({ default: () => DEFAULT_TIME_RANGE, type: Array }) value: TimeRangeType; // 组件回显值
  @Prop({ default: 'normal', type: String }) type: TimeRangeDisplayType; // 组件的样式类型
  @Prop({ default: 'bottom-end', type: String }) placement: String; // 参照组件库的date-picker

  /** 本地值存储 */
  localValue: TimeRangeType = DEFAULT_TIME_RANGE;

  /** date-picker值 */
  timestamp: TimeRangeType = ['', ''];

  /** 选中时间展示 */
  timeDisplay = '';

  /** 是否展示面板 */
  isShow = false;

  /** 是否展示面板的时间段 */
  isPanelTimeRange = false;

  /** 时间快捷选项 */
  shortcuts = shortcuts;

  /** 快捷选项映射表 */
  get shortcutsMap() {
    return this.shortcuts.reduce((map, cur) => {
      map.set(cur.value.join(' -- '), cur.text);
      return map;
    }, new Map());
  }

  @Watch('value', { immediate: true, deep: true })
  valueChange(val: TimeRangeType) {
    this.localValue = [...val];
    this.handleTransformTime();
    this.updateTimeDisplay();
  }

  /** 将value转换成时间区间 */
  handleTransformTime(value: TimeRangeType = this.value) {
    const dateArr = handleTransformTime(value);
    this.timestamp = [dateArr[0], dateArr[1]];
  }

  /** 面板选择时间范围 */
  dateTimeChange(date: [string, string]) {
    this.timestamp = date.map((item, index) => `${item} ${!index ? '00:00:00' : '23:59:59'}`) as TimeRangeType;
    this.localValue = [...this.timestamp];
    this.isPanelTimeRange = true;
  }

  /** 确认操作 */
  @Emit('change')
  handleTimeRangeChange() {
    this.$nextTick(() => {
      this.isShow = false;
    });
    this.handleTransformTime(this.timestamp);
    return this.isPanelTimeRange ? this.timestamp : this.formatTime(this.localValue);
  }

  /** 格式化绝对时间点 */
  formatTime(value: TimeRangeType) {
    return value.map(item => {
      const m = moment(intTimestampStr(item));
      return m.isValid() ? m.format('YYYY-MM-DD HH:mm:ss') : item;
    });
  }

  /** 时间面板展开收起 */
  handlePanelShowChange(val: boolean) {
    this.isShow = val;
    if (val) {
      this.isPanelTimeRange = false;
      this.valueChange(this.value);
    }
  }

  /** 更新时间展示 */
  updateTimeDisplay() {
    const timeArr = this.isPanelTimeRange ? this.timestamp : this.value;
    this.timeDisplay = timeArr.join(' -- ');
    if (this.shortcutsMap.get(this.timeDisplay)) {
      this.timeDisplay = this.shortcutsMap.get(this.timeDisplay);
    }
  }

  /** 点击快捷时间选项 */
  handleShortcutChange(data) {
    if (!!data?.value) {
      this.isPanelTimeRange = false;
      const value = [...data.value] as TimeRangeType;
      this.handleTransformTime(value);
      this.localValue = value;
      this.handleTimeRangeChange();
    }
  }

  /** 校验之间范围的合法性 */
  handleValidateTimeRange(): boolean {
    const timeRange = handleTransformToTimestamp(this.localValue);
    /** 时间格式错误 */
    if (timeRange.some(item => !item)) return false;
    /** 时间范围有误 */
    if (timeRange[0] > timeRange[1]) return false;
    return true;
  }
  /** 确认操作 */
  handleConfirm() {
    const pass = this.handleValidateTimeRange();
    if (!pass) {
      this.localValue = [...this.value];
      this.isShow = false;
    } else {
      this.handleTimeRangeChange();
    }
  }

  /**
   * 自定义输入时间范围
   * @param index 值索引
   */
  handleCustomInput(index: number) {
    this.isPanelTimeRange = false;
    if (!this.localValue[index]) {
      this.$set(this.localValue, index, moment().format('YYYY-MM-DD HH:mm:ss'));
    }
  }

  render() {
    /** 语法格式提示 */
    const customDescTpl = (id: string) => (
      <div style={{ display: 'none' }}>
        <div
          id={id}
          class='time-range-desc-wrap'
        >
          <div class='desc-row'>{`${this.$t('完整格式')}: ${moment().format('YYYY-MM-DD HH:mm:ss')}`}</div>
          <div class='desc-row'>
            {`${this.$t('快捷格式')}: m ${this.$t('分钟')}, h ${this.$t('小时')}, d ${this.$t('天')}, w ${this.$t(
              '周'
            )}, M ${this.$t('月')}`}
          </div>
        </div>
      </div>
    );
    return (
      <div class={['time-range-wrap', { 'time-range-input-wrap': this.type === 'input' }]}>
        <bk-date-picker
          class='date-picker'
          ext-popover-cls='time-range-popover'
          value={this.timestamp}
          open={this.isShow}
          type='daterange'
          transfer
          placement={this.placement}
          on-change={this.dateTimeChange}
          on-open-change={this.handlePanelShowChange}
        >
          <bk-popover
            slot='trigger'
            zIndex={4004}
            placement='bottom'
            tippy-options={{
              onShow: () => {
                /** 防止代码自动格式化 */
                this.handleTransformTime();
              }
            }}
            theme='light time-range-tips'
          >
            {!window.__BK_WEWEB_DATA__?.lockTimeRange &&
              (() => {
                if (this.type === 'input') {
                  return (
                    <div
                      class={['time-range-trigger', 'input-type', { active: this.isShow }]}
                      onClick={() => (this.isShow = true)}
                    >
                      <span class='icon-monitor icon-mc-time'></span>
                      <span class='time-range-text'>{this.timeDisplay}</span>
                    </div>
                  );
                }
                return (
                  <div
                    class={[
                      'time-range-trigger',
                      { active: this.isShow, simple: this.type === 'simple', border: this.type === 'border' }
                    ]}
                    onClick={() => (this.isShow = true)}
                  >
                    <span class='icon-monitor icon-mc-time'></span>
                    {this.type !== 'simple' && <span class='time-range-text'>{this.timeDisplay}</span>}
                    {this.type !== 'normal' && <i class='bk-icon icon-angle-down'></i>}
                  </div>
                );
              })()}
            <div
              slot='content'
              class='time-range-tips-content'
            >
              <div>{this.timestamp[0]}</div>
              <div>to</div>
              <div>{this.timestamp[1]}</div>
            </div>
          </bk-popover>
          <div
            slot='header'
            class='time-range-custom'
            onMousedown={modifiers.stop(() => {})}
          >
            {customDescTpl('time-range-desc-left')}
            {customDescTpl('time-range-desc-right')}
            <i18n
              path='从 {0} 至 {1}'
              tag={false}
            >
              <bk-input
                class='custom-input'
                v-model={this.localValue[0]}
                v-bk-tooltips={{
                  allowHtml: true,
                  theme: 'light',
                  content: '#time-range-desc-left',
                  placement: 'bottom'
                }}
                onInput={() => this.handleCustomInput(0)}
                clearable
              />
              <bk-input
                class='custom-input'
                v-model={this.localValue[1]}
                v-bk-tooltips={{
                  allowHtml: true,
                  theme: 'light',
                  content: '#time-range-desc-right',
                  placement: 'bottom'
                }}
                onInput={() => this.handleCustomInput(1)}
                clearable
              />
            </i18n>
          </div>
          <div
            slot='footer'
            class='time-range-footer'
          >
            <bk-button
              theme='primary'
              onClick={this.handleConfirm}
            >
              {this.$t('确定')}
            </bk-button>
          </div>
          <ul
            slot='shortcuts'
            class='shortcuts-list'
          >
            {this.shortcuts.map(item => (
              <li
                class='shortcuts-item'
                onClick={() => this.handleShortcutChange(item)}
              >
                {item.text}
              </li>
            ))}
          </ul>
        </bk-date-picker>
      </div>
    );
  }
}
