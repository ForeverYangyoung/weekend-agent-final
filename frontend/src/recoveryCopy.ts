/** 把后端预检/恢复 trace 转成用户能看懂的说明。 */
export function humanizeRecoveryReason(raw: string): string {
  const body = raw.replace(/^\[[^\]]+\]\s*/, '').trim()
  if (/正在帮您换一家|正在自动换备选|正在调整搭配/.test(body)) {
    return `${body}，稍等片刻就好。`
  }

  const shopMatch = body.match(/「([^」]+)」/) ?? body.match(/([^|(（]+)(?:（[^）]+）)?\s*\(poi_/)
  const shop = (shopMatch?.[1] ?? shopMatch?.[0] ?? '这家餐厅').trim()

  if (/满座|桌位不可用|4人桌已满/.test(body)) {
    return `「${shop}」刚才 4 人桌满了。系统会自动帮您换一家口碑相近的店，稍等片刻就好。`
  }
  if (/库存不足|售罄|没货/.test(body)) {
    return `「${shop}」的加餐/饮品暂时没货了，系统正在帮您调整搭配。`
  }
  return body || '有部分行程预订没通过，系统正在自动帮您调整，不用您重复操作。'
}

export function traceHadAutoRecovery(trace: string[]): boolean {
  return trace.some(
    (line) =>
      /换一家|换备选|满座|订不到了|自动换店|dry_run_recovery/i.test(line),
  )
}
