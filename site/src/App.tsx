import { Hero } from './components/Hero'
import { ProofStrip } from './components/ProofStrip'
import { TopBar } from './components/TopBar'

export default function App() {
  return (
    <>
      <div className="mx-auto max-w-[1180px] px-6">
        <TopBar />
        <Hero />
      </div>
      <div className="mx-auto max-w-[1180px] px-6">
        <ProofStrip />
      </div>
    </>
  )
}
