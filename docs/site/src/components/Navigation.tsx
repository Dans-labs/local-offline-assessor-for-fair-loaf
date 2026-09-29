'use client'

import clsx from 'clsx'
import { AnimatePresence, motion } from 'framer-motion'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useRef } from 'react'

import { GitHubIcon } from '@/components/GitHubIcon'
import { useIsInsideMobileNavigation } from '@/components/MobileNavigation'
import { useSectionStore, type Section } from '@/components/SectionProvider'
import { Tag } from '@/components/Tag'
import { CloseButton } from '@headlessui/react'

interface NavItem {
  title: string
  href: string
  children?: Array<NavItem>
  tag?: string
}

interface NavGroup {
  title: string
  links: Array<NavItem>
}

export function findNavigationPath(
  links: Array<NavItem>,
  href: string,
): Array<NavItem> | undefined {
  for (const link of links) {
    if (link.href === href) return [link]
    const childPath = findNavigationPath(link.children ?? [], href)
    if (childPath) return [link, ...childPath]
  }
}

function useInitialValue<T>(value: T, condition = true) {
  // eslint-disable-next-line react-hooks/refs
  let initialValue = useRef(value).current
  return condition ? initialValue : value
}

function TopLevelNavItem({
  href,
  children,
}: {
  href: string
  children: React.ReactNode
}) {
  return (
    <li className="md:hidden">
      <CloseButton
        as={Link}
        href={href}
        className="block py-1 text-sm text-zinc-600 transition hover:text-brand-950 dark:text-zinc-400 dark:hover:text-white"
      >
        {children}
      </CloseButton>
    </li>
  )
}

function NavLink({
  href,
  children,
  tag,
  active = false,
  visible = false,
}: {
  href: string
  children: React.ReactNode
  tag?: string
  active?: boolean
  visible?: boolean
}) {
  return (
    <CloseButton
      as={Link}
      href={href}
      aria-current={active ? 'page' : undefined}
      className={clsx(
        'relative flex justify-between gap-2 rounded-r-lg py-1 pr-3 pl-4 text-sm transition',
        (active || visible) && 'bg-zinc-800/2.5 dark:bg-white/2.5',
        active &&
          'before:absolute before:inset-y-1 before:-left-px before:w-px before:bg-brand-500',
        active
          ? 'text-brand-950 dark:text-white'
          : 'text-zinc-600 hover:text-brand-950 dark:text-zinc-400 dark:hover:text-white',
      )}
    >
      <span>{children}</span>
      {tag && (
        <Tag variant="small" color="zinc">
          {tag}
        </Tag>
      )}
    </CloseButton>
  )
}

function sectionNavigation(sections: Array<Section>, href: string) {
  const links: Array<NavItem> = []
  for (const section of sections) {
    const link: NavItem = {
      title: section.title,
      href: `${href}#${section.id}`,
      tag: section.tag,
    }
    const parent = links.at(-1)
    if (section.level === 3 && parent) {
      ;(parent.children ??= []).push(link)
    } else {
      links.push(link)
    }
  }
  return links
}

function NavigationItem({
  link,
  pathname,
  sections,
  visibleSections,
}: {
  link: NavItem
  pathname: string
  sections: Array<Section>
  visibleSections: Array<string>
}) {
  const active = link.href === pathname
  const children = active
    ? sectionNavigation(sections, link.href)
    : link.children

  return (
    <motion.li layout="position" className="relative">
      <NavLink
        href={link.href}
        active={active}
        tag={link.tag}
        visible={visibleSections.includes(link.href.split('#')[1])}
      >
        {link.title}
      </NavLink>
      <AnimatePresence mode="popLayout" initial={false}>
        {children && children.length > 0 && (
          <motion.ul
            role="list"
            className="ml-4 border-l border-brand-950/10 dark:border-white/5"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1, transition: { delay: 0.1 } }}
            exit={{ opacity: 0, transition: { duration: 0.15 } }}
          >
            {children.map((child) => (
              <NavigationItem
                key={child.href}
                link={child}
                pathname={pathname}
                sections={sections}
                visibleSections={visibleSections}
              />
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </motion.li>
  )
}

function NavigationGroup({
  group,
  className,
}: {
  group: NavGroup
  className?: string
}) {
  // If this is the mobile navigation then we always render the initial
  // state, so that the state does not change during the close animation.
  // The state will still update when we re-open (re-render) the navigation.
  let isInsideMobileNavigation = useIsInsideMobileNavigation()
  let [pathname, sections, visibleSections] = useInitialValue(
    [
      usePathname().replace(/\/$/, '') || '/',
      useSectionStore((s) => s.sections),
      useSectionStore((s) => s.visibleSections),
    ],
    isInsideMobileNavigation,
  )

  return (
    <li className={clsx('relative mt-6', className)}>
      <motion.h2
        layout="position"
        className="text-xs font-semibold text-brand-950 dark:text-white"
      >
        {group.title}
      </motion.h2>
      <ul
        role="list"
        className="mt-3 ml-2 border-l border-brand-950/10 dark:border-white/5"
      >
        {group.links.map((link) => (
          <NavigationItem
            key={link.href}
            link={link}
            pathname={pathname}
            sections={sections}
            visibleSections={visibleSections}
          />
        ))}
      </ul>
    </li>
  )
}

export const navigation: Array<NavGroup> = [
  {
    title: 'Getting started',
    links: [
      { title: 'Introduction', href: '/' },
      { title: 'Quickstart', href: '/quickstart' },
    ],
  },
  {
    title: 'Reference',
    links: [
      { title: 'Python API', href: '/reference' },
      { title: 'Results', href: '/results' },
    ],
  },
  {
    title: 'Assessors',
    links: [
      {
        title: 'F-UJI',
        href: '/assessors/fuji',
      },
      {
        title: 'FAIR Champion',
        href: '/assessors/champion',
      },
    ],
  },
]

export function Navigation(props: React.ComponentPropsWithoutRef<'nav'>) {
  return (
    <nav {...props}>
      <ul role="list">
        <TopLevelNavItem href="https://github.com/Dans-labs/local-offline-assessor-for-fair-loaf">
          <GitHubIcon className="size-5" />
          <span className="sr-only">GitHub</span>
        </TopLevelNavItem>
        {navigation.map((group, groupIndex) => (
          <NavigationGroup
            key={group.title}
            group={group}
            className={groupIndex === 0 ? 'md:mt-0' : ''}
          />
        ))}
      </ul>
    </nav>
  )
}
