// ATM Glossary adaptations, 2026. SPDX-License-Identifier: Apache-2.0
package org.mcxa.icaoglossary

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import org.mcxa.icaoglossary.databinding.TermItemBinding

class TermAdapter(private val onSelect: (Term) -> Unit) : ListAdapter<Term, TermAdapter.Holder>(
    object : DiffUtil.ItemCallback<Term>() {
        /** Recognizes the same glossary entry by its stable ID. */
        override fun areItemsTheSame(oldItem: Term, newItem: Term) = oldItem.id == newItem.id
        /** Checks every term field to decide whether its row needs updating. */
        override fun areContentsTheSame(oldItem: Term, newItem: Term) = oldItem == newItem
    }
) {
    class Holder(val binding: TermItemBinding) : RecyclerView.ViewHolder(binding.root)
    /** Inflates the XML layout for a search-result row. */
    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) = Holder(
        TermItemBinding.inflate(LayoutInflater.from(parent.context), parent, false))
    /** Displays the term, favourite marker, and source summary, and connects the selection action. */
    override fun onBindViewHolder(holder: Holder, position: Int) {
        val term = getItem(position)
        val title = term.abbreviation.ifBlank { term.meaning }
        holder.binding.title.text = if (term.favourite)
            holder.itemView.context.getString(R.string.saved_title, title) else title
        holder.binding.meaning.text = term.meaning
        holder.binding.meaning.visibility = if (term.abbreviation.isBlank()) android.view.View.GONE else android.view.View.VISIBLE
        holder.binding.provenance.text = SourceCatalog.summary(term.source, limit = 2)
        holder.binding.root.setOnClickListener { onSelect(term) }
    }
}
