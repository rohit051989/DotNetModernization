import { useState } from 'react'
import { PatternList } from './catalog/PatternList'
import { PatternDetail } from './catalog/PatternDetail'
import { EmptyState } from '../components/EmptyState'

export function CatalogPage() {
  const [selectedPatternId, setSelectedPatternId] = useState<string | null>(null)

  return (
    <div className="flex h-full">
      <PatternList selectedPatternId={selectedPatternId} onSelectPattern={setSelectedPatternId} />
      <div className="flex-1 overflow-y-auto">
        {selectedPatternId ? (
          <PatternDetail patternId={selectedPatternId} />
        ) : (
          <EmptyState
            title="Select a pattern"
            description="Choose a pattern from the list on the left to see its details."
          />
        )}
      </div>
    </div>
  )
}
