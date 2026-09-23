'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

export default function TroubleshootingRedirect() {
  const router = useRouter()

  useEffect(() => {
    router.replace(
      `/assessors/fuji${window.location.hash || '#troubleshooting'}`,
    )
  }, [router])

  return (
    <p className="py-16">
      Troubleshooting is now part of the{' '}
      <Link href="/assessors/fuji#troubleshooting">F-UJI page</Link>.
    </p>
  )
}
