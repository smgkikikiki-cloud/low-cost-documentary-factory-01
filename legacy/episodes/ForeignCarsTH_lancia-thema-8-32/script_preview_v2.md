# A-FINAL Preview Script v2 — Lancia Thema 8.32

**Status: PREVIEW TEST ONLY — not `final_script.json`.**

Regression run after the A-FINAL editorial patch to
`agents/agent_a_producer_writer.md` (new "A-FINAL writing" section: *airable
means eligible, not mandatory* + *keep research uncertainty backstage*). Same
inputs as `script_preview.md` — `fact_pack.json` (`status: verified`),
`producer_outline.json`, channel config — no new research. Still an
out-of-sequence A-FINAL run before Agent B; the real A-FINAL gate is
untouched and `final_script.json` was not written to. This version does not
overwrite `script_preview.md`.

Each beat is followed by an italicized audit note: claims used, claims
deliberately dropped, and why.

---

## Beat 1 — Cold Open

ลองนึกภาพรถเก๋งอิตาลีคันหนึ่ง จอดอยู่ข้างถนนธรรมดา ๆ ทรงตัวถังสามตอนคลาสสิกแบบซีดานยุค 80 ไม่มีสปอยเลอร์ใหญ่โต ไม่มีสติกเกอร์หรือป้ายบอกอะไรเป็นพิเศษ มองผ่าน ๆ คุณอาจเดินผ่านไปโดยไม่สนใจมันเลยด้วยซ้ำ

แต่ถ้าเปิดฝากระโปรงหน้าดู สิ่งที่จะเจอคือเครื่องยนต์ V8 ขนาด 2.9 ลิตร ที่ไม่ได้แค่ "มีกลิ่นอาย" ของแฟร์รารี แต่หล่อขึ้นจากโรงหล่อของแฟร์รารีเองที่มาราเนลโล เป็นเครื่องแฟร์รารีของแท้ ไม่ใช่เครื่องเลียนแบบ ในเวอร์ชันไม่มีแคตาไลติก มันให้กำลังถึง 215 แรงม้า พาซีดานธรรมดาคันนี้วิ่งจาก 0 ถึง 100 กิโลเมตรต่อชั่วโมงได้ในเวลาไม่ถึงเจ็ดวินาที

คำถามที่น่าสนใจกว่านั้นคือ เครื่องแฟร์รารีตัวนี้ที่ถูกยัดใส่ในซีดานธรรมดา มันยังเป็น "แฟร์รารี" อยู่แค่ไหนกันแน่

*Audit: eng01_ferrari_cast_origin, eng04_power_output, perf01_acceleration_top_speed. No change from v1 -- already selective, no process language to strip.*

---

## Beat 2 — Origin Story (compressed)

ก่อนจะไปถึงเรื่องเครื่องยนต์ ต้องถามก่อนว่าใครเป็นคนคิดไอเดียนี้ขึ้นมา คำตอบยังเป็นที่ถกเถียงกันอยู่ — แหล่งข่าวฝรั่งเศสบางส่วนให้เครดิตกับอ็องเดร ชาร์ดอนเนต์ ผู้นำเข้ารถลันชาในฝรั่งเศส ขณะที่แหล่งข่าวอังกฤษบางแห่งให้เครดิตกับวิตตอริโอ กีเดลลา ซีอีโอเฟียตกรุ๊ปในตอนนั้น ว่าเป็นคนผลักดันโปรเจกต์นี้ด้วยตัวเอง เรื่องนี้ยังไม่มีข้อสรุปที่แน่ชัด

*Audit: dev01_chardonnet_attribution, dev02_ghidella_attribution. Kept -- this is the "disagreement is itself part of the story" case the patch calls out by name -- but compressed from a full paragraph (v1) to three sentences with the minimum hedge ("ยังเป็นที่ถกเถียงกันอยู่" / "ยังไม่มีข้อสรุปที่แน่ชัด"). Cut entirely: v1's explanation that "neither source cites evidence for its own claim" -- that's methodology, not story.*

---

## Beat 3 — The De-Ferraried Ferrari (Thesis)

กลับมาที่คำถามเมื่อครู่ เครื่องยนต์ตัวนี้ "แฟร์รารี" แค่ไหนกันแน่ คำตอบที่ตรงไปตรงมาที่สุดคือ มันแฟร์รารีจริง ๆ ไม่ใช่แค่ในนาม บล็อกเครื่องถูกหล่อขึ้นที่มาราเนลโล จากนั้นถูกส่งไปให้ดูคาติเป็นผู้ประกอบ ก่อนจะถูกนำไปติดตั้งลงตัวรถที่โรงงานซานเปาโลของลันชาเองในเมืองตูริน เครื่องยนต์ตัวเดียวนี้ต้องเดินทางผ่านมือของสามบริษัทที่แตกต่างกันโดยสิ้นเชิง กว่าจะไปจบลงอยู่ในรถคันหนึ่ง รหัสเครื่อง F105L ตัวนี้ มีรากฐานเดียวกับเครื่องที่ใช้ในแฟร์รารี 308 และ Mondial Quattrovalvole

แต่สิ่งที่ทำให้เรื่องนี้น่าสนใจกว่าจะพูดสั้น ๆ แค่ว่า "มันใช้เครื่องแฟร์รารี" คือสิ่งที่ลันชาและดูคาติจงใจเปลี่ยนแปลง พวกเขาเปลี่ยนเพลาข้อเหวี่ยงจากแบบ flat-plane ที่รถสปอร์ตแฟร์รารียุคนั้นใช้กันเป็นมาตรฐาน มาเป็นแบบ cross-plane เปลี่ยนขนาดวาล์วให้เล็กลง และเปลี่ยนลำดับการจุดระเบิดใหม่ทั้งหมด เพลาแบบ flat-plane คือสิ่งที่ทำให้แฟร์รารีมีเสียงคำรามและตอบสนองแบบรถสปอร์ตรอบสูง ส่วนเพลาแบบ cross-plane ที่ลันชาเลือกใช้ ให้แรงบิดที่มาไวและนุ่มนวลกว่าในรอบต่ำ เหมาะกับรถซีดานสี่ประตูขับเคลื่อนล้อหน้า มากกว่าจะเป็นรถสปอร์ตเครื่องกลางลำแบบต้นตำรับ

พูดอีกแบบหนึ่งก็คือ นี่คือเครื่องยนต์แฟร์รารีของแท้ ที่ถูกวิศวกรออกแบบใหม่อย่างตั้งใจ เพื่อให้มันไม่รู้สึกเหมือนแฟร์รารีอีกต่อไป

*Audit: eng01_ferrari_cast_origin, eng03_assembly_process, eng02_deferraried_modifications. Unchanged from v1 -- this is the thesis beat; nothing here is low-value or redundant, all three claims are load-bearing.*

---

## Beat 4 — What It Cost and Came With

แล้วคนที่ยอมจ่ายเงินซื้อรถคันนี้ ได้อะไรกลับไปบ้าง ตัวถังซาลูนออกแบบโดยจอร์เจตโต จูจาโร และสตูดิโอ Italdesign ภายในมาพร้อมสปอยเลอร์หลังแบบยืดหด-เก็บได้ที่ควบคุมจากในรถ เบรก ABS พวงมาลัยพาวเวอร์ และห้องโดยสารบุด้วยไม้และผ้า Alcantara แต่มีเกียร์ธรรมดาห้าสปีดให้เลือกเพียงแบบเดียว ไม่เคยมีเกียร์อัตโนมัติให้เลือกเลยตลอดทั้งรุ่น

ส่วนเรื่องราคา ในอังกฤษปี 1988 มันตั้งราคาไว้ที่ 37,500 ปอนด์ เทียบกับ Thema รุ่นพื้นฐานที่สุดในตลาดเดียวกันปีเดียวกัน ซึ่งอยู่ที่ 12,495 ปอนด์ นั่นคือแพงกว่ากันราวสามเท่าตัว ไม่ใช่แค่เกือบสองเท่าอย่างที่หลายคนอาจคาดเดาไว้

*Audit: des01_designer_credit, eq01_standard_features, price01_uk_1988_price, d02_price_premium_vs_base. Two cuts from v1: (1) the Pininfarina-wagon aside from des01 -- true but tangential to the thesis, no story value here; (2) the paragraph explaining we couldn't find an Italian domestic price and don't know if £37,500 reflects import cost -- that's the research process, not the history. The accuracy safeguard (never implying £37,500 was the Italian list price) is kept via the economical "ในอังกฤษปี 1988" market/year scoping itself, per price01/d02's forbidden_or_unsupported_inference, without narrating why.*

---

## Beat 5 — Reception (compressed to one beat)

ในแวดวงสื่อรถยนต์ นิตยสาร Road & Track ของอเมริกา เคยเขียนถึงมันในภายหลังว่าเป็น "หนึ่งในรถหน้าตาธรรมดาแต่ซ่อนของแรงที่แปลกประหลาดที่สุดจากยุค 1980s" เป็นมุมมองที่มองย้อนกลับไป ไม่ใช่ปฏิกิริยาตอนรถยังใหม่

*Audit: rec01_road_and_track_retrospective only. rec02_quattroruote_existence is dropped entirely from this version -- v1 spent a full sentence establishing that an Italian test existed but its content was inaccessible, which is exactly the "we could not access X" pattern the patch prohibits. Knowing a test ran with no way to characterize it has no narrative payoff, so per the new "cut it" rule this beat is effectively reduced to the one quote that does have story value, rather than padded to cover both supporting_claim_ids.*

---

## Beat 6 — Legacy

ตลอดสายการผลิตทั้งสองซีรีส์ ลันชาสร้าง 8.32 ออกมารวมทั้งสิ้น 3,971 คัน แบ่งเป็นซีรีส์แรก 2,370 คัน ระหว่างปี 1986 ถึง 1988 และซีรีส์สอง อีก 1,601 คัน ผลิตต่อเนื่องไปจนถึงปี 1992 รถทุกคันเป็นพวงมาลัยซ้ายทั้งหมด ไม่เคยมีรุ่นพวงมาลัยขวาออกจากโรงงานเลยสักคันเดียว

และมีเรื่องเล่าปิดท้ายที่น่าจดจำอยู่เรื่องหนึ่ง ว่ากันว่าเอนโซ แฟร์รารี เจ้าของแฟร์รารีเอง ก็เคยเก็บ 8.32 คันหนึ่งไว้ใช้เป็นรถส่วนตัวในช่วงบั้นปลายชีวิต ชายที่ชื่อของเขาถูกหล่อลงไปในเนื้อบล็อกเครื่องยนต์ตัวนี้เอง กลับเลือกที่จะขับรถคันที่ไม่มีตราม้าลำพองติดอยู่แม้แต่ตัวเดียว

*Audit: prod01_series1_count, prod02_series2_count, prod03_total_stated, d01_total_arithmetic_check, own02_uk_lhd_only, own01_enzo_ferrari_ownership. Unchanged from v1 -- all high confidence, well-corroborated, each earns its place in the closing beat.*

---

## Editorial decisions in this pass (summary)

- **Cut entirely:** `rec02_quattroruote_existence` (existence-only, unresolved, no
  story payoff without content -- narrating it would just be narrating an access
  failure). Also cut the Pininfarina-wagon aside from `des01` (true but tangential).
- **Compressed, kept:** the dev01/dev02 origin dispute (Beat 2) -- this is the one
  case in this episode where the uncertainty is itself part of the history, so it's
  narrated, but in three economical sentences instead of a full paragraph, with no
  explanation of why the sources are thin.
- **Cut the methodology, kept the fact:** the UK/1988 price (Beat 4) is stated with
  its market/year scoped plainly, but the paragraph explaining the failed search for
  an Italian price is gone -- the scoping itself is the hedge; no need to narrate the
  research gap behind it.
- **Deliberately uneven beat lengths:** Beat 3 (thesis) is the longest and richest;
  Beats 2 and 5 are now short by design, reflecting thinner/less story-relevant
  evidence rather than being padded to match the others.
- **Unchanged:** Beats 1, 3, and 6 -- already selective in v1, nothing to cut.
