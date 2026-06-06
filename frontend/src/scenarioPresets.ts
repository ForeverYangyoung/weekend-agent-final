import type { ProfileChip } from './types'

export type ScenarioId = 'family' | 'friends'

export interface ScenarioPreset {
  id: ScenarioId
  title: string
  subtitle: string
  basePrompt: string
  defaultChips: ProfileChip[]
  panelPrefs: {
    distance: string
    diet: string
    vibe: string
  }
}

export const SCENARIO_PRESETS: Record<ScenarioId, ScenarioPreset> = {
  family: {
    id: 'family',
    title: '家庭场景',
    subtitle: '3 人 · 5 岁娃 · 可再加火锅/轻食等偏好',
    basePrompt: '今天下午带老婆孩子出去玩，孩子5岁，别太远，帮我安排一下',
    defaultChips: [
      { key: 'scene', label: '家庭', value: 'family', source: 'utterance', editable: true },
      { key: 'people_count', label: '3 人', value: '3', source: 'utterance', editable: true },
      { key: 'kids_ages', label: '孩子 5岁', value: '5', source: 'utterance', editable: true },
      { key: 'distance_limit_km', label: '≤ 10 km', value: '10', source: 'utterance', editable: true },
      { key: 'interests', label: '亲子', value: '亲子', source: 'utterance', editable: true },
    ],
    panelPrefs: { distance: '10公里内', diet: '轻食', vibe: '亲子' },
  },
  friends: {
    id: 'friends',
    title: '朋友场景',
    subtitle: '4 人 · 重口味 · Zero-Skill 档案 Mock + 满座 Recovery',
    basePrompt: '下午和三个朋友一起出去，4个人，别太远，想吃重口味，帮我安排一下',
    defaultChips: [
      { key: 'scene', label: '朋友', value: 'friends', source: 'utterance', editable: true },
      { key: 'people_count', label: '4 人', value: '4', source: 'utterance', editable: true },
      { key: 'distance_limit_km', label: '≤ 8 km', value: '8', source: 'utterance', editable: true },
      { key: 'dietary', label: '重口味', value: '重口味', source: 'utterance', editable: true },
      { key: 'interests', label: '轻松社交', value: '轻松社交', source: 'utterance', editable: true },
    ],
    panelPrefs: { distance: '8公里内', diet: '重口味', vibe: '轻松社交' },
  },
}
