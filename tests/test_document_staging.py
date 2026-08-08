import pytest

from flask_postgresql_audit.extensions.document_staging import Docstatus

from .app import Document, db


@pytest.mark.usefixtures("test_client")
class TestDocumentStaging:
    def test_document_creation(self):
        doc = Document(title="Doc 1")
        db.session.add(doc)
        db.session.commit()

        assert doc.docstatus == Docstatus.DRAFT
        assert doc.created_by == "test_actor"
        assert doc.created_on is not None

    def test_document_bump_lifecycle(self):
        doc = Document(title="Doc 2")
        db.session.add(doc)
        db.session.commit()

        # DRAFT -> SUBMITTED
        doc.bump()
        db.session.commit()
        assert doc.docstatus == Docstatus.SUBMITTED
        assert doc.submitted_by == "test_actor"
        assert doc.submitted_on is not None

        # SUBMITTED -> CANCELLED
        doc.bump()
        db.session.commit()
        assert doc.docstatus == Docstatus.CANCELLED
        assert doc.cancelled_by == "test_actor"
        assert doc.cancelled_on is not None

        # Bumping CANCELLED raises ValueError
        with pytest.raises(ValueError, match="cannot be bumped"):
            doc.bump()

    def test_document_revise(self):
        doc1 = Document(title="Original")
        db.session.add(doc1)
        db.session.commit()

        # Cannot revise DRAFT
        with pytest.raises(ValueError, match="cannot be revised"):
            doc1.revise(Document(title="V2"))

        doc1.bump()  # SUBMITTED
        doc1.bump()  # CANCELLED
        db.session.commit()

        doc2 = Document(title="V2")
        revised_doc = doc1.revise(doc2)
        db.session.add(revised_doc)
        db.session.commit()

        assert doc1.docstatus == Docstatus.REVISED
        assert doc1.revision == doc2
        assert doc2.revision_of == doc1
        assert doc2.docstatus == Docstatus.DRAFT

    def test_document_delete(self):
        # Delete DRAFT
        doc = Document(title="Draft to delete")
        db.session.add(doc)
        db.session.commit()
        doc_id = doc.id

        doc.delete(db.session)
        db.session.commit()

        assert db.session.get(Document, doc_id) is None

        # Delete non-DRAFT raises ValueError
        doc_submitted = Document(title="Submitted")
        db.session.add(doc_submitted)
        db.session.commit()
        doc_submitted.bump()
        db.session.commit()

        with pytest.raises(ValueError, match="cannot be deleted"):
            doc_submitted.delete(db.session)

    def test_delete_revision_reverts_parent_status(self):
        doc1 = Document(title="Original")
        db.session.add(doc1)
        db.session.commit()
        doc1.bump()
        doc1.bump()  # CANCELLED
        db.session.commit()

        doc2 = Document(title="V2 Revision")
        doc1.revise(doc2)
        db.session.add(doc2)
        db.session.commit()

        assert doc1.docstatus == Docstatus.REVISED

        # Delete revision doc2
        doc2.delete(db.session)
        db.session.commit()

        assert doc1.docstatus == Docstatus.CANCELLED
