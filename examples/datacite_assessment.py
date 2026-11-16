from fair_offline_assessor import FairAssessor

xml = """\
<record xmlns="http://www.openarchives.org/OAI/2.0/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <header>
    <identifier>n4e/dthb-oai-pangaea.de-doi-10.1594-PANGAEA.619420</identifier>
    <datestamp>2007-06-28</datestamp>
  </header>
  <metadata>
    <resource xmlns="http://datacite.org/schema/kernel-4" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://datacite.org/schema/kernel-4 https://schema.datacite.org/meta/kernel-4.6/metadata.xsd">
      <identifier identifierType="DOI">10.1594/PANGAEA.619420</identifier>
      <creators>
        <creator>
          <creatorName>Jutta Hofmann</creatorName>
        </creator>
      </creators>
      <titles>
        <title>Tree-ring width of Abies alba (Miller) from historical object sample HOF10906-21</title>
      </titles>
      <publisher>https://cordra.knowledgehub.nfdi4earth.de/objects/n4e/ror-032e6b942</publisher>
      <publicationYear>2007</publicationYear>
      <resourceType resourceTypeGeneral="Dataset">Dataset</resourceType>
      <dates>
        <date dateType="Issued">2007-06-28</date>
      </dates>
      <relatedIdentifiers>
        <relatedIdentifier relatedIdentifierType="URL" relationType="IsSourceOf">https://doi.pangaea.de/10.1594/PANGAEA.619420?format=textfile</relatedIdentifier>
      </relatedIdentifiers>
      <subjects>
        <subject>HISTRA</subject>
        <subject>Historical object</subject>
        <subject>TreeRings_SouthGermany</subject>
        <subject>Zooplankton</subject>
      </subjects>
    </resource>
  </metadata>
</record>
"""

result = FairAssessor().assess(
    metadata=xml,
    metadata_format="xml",
)

print(result.model_dump_json(indent=2))
